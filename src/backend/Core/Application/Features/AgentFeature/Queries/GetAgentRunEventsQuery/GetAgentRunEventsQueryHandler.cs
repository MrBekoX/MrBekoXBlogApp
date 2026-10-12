using BlogApp.Core.Application.Common.Errors;
using BlogApp.Core.Application.Common.Interfaces.Data;
using BlogApp.Core.Application.Common.Interfaces.Services;
using BlogApp.Core.Application.Common.Messaging;
using BlogApp.Core.Application.Common.Models;
using BlogApp.Core.Application.Features.AgentFeature.Queries.GetAgentRunQuery;
using MediatR;
using Microsoft.EntityFrameworkCore;

namespace BlogApp.Core.Application.Features.AgentFeature.Queries.GetAgentRunEventsQuery;

/// <summary>Tek replay olayı: commit edilmiş projection inbox kaydından (B5).
/// Yalnız ``applied`` kayıtlar replay edilir; stale/quarantined projection'a
/// uygulanmadığı için olay akışının parçası değildir.</summary>
public sealed record AgentRunEventDto
{
    public required long EventSequence { get; init; }

    public required string MessageType { get; init; }

    public required string MessageId { get; init; }

    public required DateTimeOffset OccurredAt { get; init; }
}

/// <summary>
/// GET /api/v1/agent/runs/{runId}/events karşılığı (B10; plan tablosu: "Yetkili
/// SSE/replay"). Kaynak COMMIT EDİLMİŞ projection'dır (agent_event_inboxes,
/// consumer backend-agent-events); SignalR canlı bildirimlerinin kopukluk
/// penceresini GET replay tamamlar (B5 hub sözleşmesinin eşdeğeri). ``after``
/// imleciyle istemci yenileme sonrası kaldığı yerden devam eder; sıralama
/// event_sequence'e göredir (projection yalnız monoton sırayla uygular).
/// </summary>
public sealed class GetAgentRunEventsQueryHandler(
    IApplicationDbContext dbContext,
    ICurrentUserService currentUser) : IRequestHandler<GetAgentRunEventsQueryRequest, Result<AgentRunEventsDto>>
{
    /// <summary>Tek replay sayfasının üst sınırı; sınırsız akış üretilmez.</summary>
    public const int MaxPageSize = 200;

    public async Task<Result<AgentRunEventsDto>> Handle(GetAgentRunEventsQueryRequest request, CancellationToken cancellationToken)
    {
        var userId = currentUser.UserId;
        var guestSessionId = request.GuestSessionId?.Trim();
        if (userId is null && string.IsNullOrWhiteSpace(guestSessionId))
        {
            return Result<AgentRunEventsDto>.Failure(Error.Unauthorized("Agent işi için oturum gereklidir."));
        }

        var ownerKey = userId is not null ? $"u:{userId.Value:D}" : $"g:{guestSessionId}";

        var run = await dbContext.AgentRuns
            .AsNoTracking()
            .FirstOrDefaultAsync(r => r.Id == request.RunId, cancellationToken);
        if (run is null)
        {
            return Result<AgentRunEventsDto>.Failure(Error.NotFound("Agent işi bulunamadı."));
        }

        if (!string.Equals(run.OwnerKey, ownerKey, StringComparison.Ordinal))
        {
            return Result<AgentRunEventsDto>.Failure(Error.Forbidden("Bu agent işi başka bir oturuma ait."));
        }

        var pageSize = request.Limit is > 0 and <= MaxPageSize ? request.Limit.Value : MaxPageSize;

        var events = await dbContext.AgentEventInboxes
            .AsNoTracking()
            .Where(i => i.ConsumerName == AgentRunEventProjectionHandler.ConsumerName
                        && i.RunId == request.RunId
                        && i.Status == "applied"
                        && i.EventSequence > request.After)
            .OrderBy(i => i.EventSequence)
            .Take(pageSize)
            .Select(i => new AgentRunEventDto
            {
                EventSequence = i.EventSequence,
                MessageType = i.MessageType,
                MessageId = i.MessageId.ToString("D"),
                OccurredAt = new DateTimeOffset(i.CreatedAt, TimeSpan.Zero),
            })
            .ToListAsync(cancellationToken);

        return Result<AgentRunEventsDto>.Success(new AgentRunEventsDto
        {
            RunId = run.Id,
            RunStatus = run.Status.ToString(),
            LastEventSequence = run.LastEventSequence,
            HasMore = events.Count == pageSize,
            Events = events,
        });
    }
}
