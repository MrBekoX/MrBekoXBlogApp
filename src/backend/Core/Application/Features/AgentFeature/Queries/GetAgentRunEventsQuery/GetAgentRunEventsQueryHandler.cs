using System.Text.Json;
using BlogApp.Core.Application.Common.Errors;
using BlogApp.Core.Application.Common.Interfaces.Data;
using BlogApp.Core.Application.Common.Interfaces.Services;
using BlogApp.Core.Application.Common.Messaging;
using BlogApp.Core.Application.Common.Models;
using BlogApp.Core.Application.Common.Options;
using BlogApp.Core.Application.Features.AgentFeature.Queries.GetAgentRunQuery;
using BlogApp.Core.Application.Features.AgentFeature.Services;
using MediatR;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Options;

namespace BlogApp.Core.Application.Features.AgentFeature.Queries.GetAgentRunEventsQuery;

/// <summary>Tek replay olayı: commit edilmiş projection inbox kaydından (B5).
/// Yalnız ``applied`` kayıtlar replay edilir; stale/quarantined projection'a
/// uygulanmadığı için olay akışının parçası değildir. Ortak olay yüzeyi alanları
/// (agent live-steps sözleşmesi, ADDITIVE): ``Kind`` progressed'te payload.kind,
/// terminal olaylarda messageType son ekinden türetilir (completed | partial |
/// failed | cancelled; agent.action.proposed → action_proposed); sözleşme dışı
/// türlerde null. ``Message`` progressed'te saklanan kullanıcı-dostu TR cümle;
/// ``Detail`` progressed payload'ının küratörlü detail sözlüğü (değer başına
/// 500 karakterle kesilir). Bozuk/eksik payload'da bu üç alan null döner — olay
/// düşmez, mevcut alanlar değişmez.</summary>
public sealed record AgentRunEventDto
{
    public required long EventSequence { get; init; }

    public required string MessageType { get; init; }

    public required string MessageId { get; init; }

    public required DateTimeOffset OccurredAt { get; init; }

    public string? Kind { get; init; }

    public string? Message { get; init; }

    public IReadOnlyDictionary<string, string>? Detail { get; init; }
}

/// <summary>
/// GET /api/v1/agent/runs/{runId}/events karşılığı (B10; plan tablosu: "Yetkili
/// SSE/replay"). Kaynak COMMIT EDİLMİŞ projection'dır (agent_event_inboxes,
/// consumer backend-agent-events); SignalR canlı bildirimlerinin kopukluk
/// penceresini GET replay tamamlar (B5 hub sözleşmesinin eşdeğeri). ``after``
/// imleciyle istemci yenileme sonrası kaldığı yerden devam eder; sıralama
/// event_sequence'e göredir (projection yalnız monoton sırayla uygular).
/// Agent live-steps olay yüzeyi (ADDITIVE): saklanan PayloadJson + ProgressMessage
/// sütunlarından kind/message/detail türetilir; türetme OKUMA yönündedir ve
/// mevcut replay davranışını değiştirmez.
/// K6: profil run'ında (konu who_am_i veya etkin kapsam profile) generation_delta olayları
/// gövdesiz döner (message/detail null) — doğrulanmamış biyografi parçası replay'de sunulmaz.
/// </summary>
public sealed class GetAgentRunEventsQueryHandler(
    IApplicationDbContext dbContext,
    ICurrentUserService currentUser,
    IAgentResultPresentationGuard presentationGuard,
    IOptions<AgentAcceptanceSettings>? acceptanceOptions = null) : IRequestHandler<GetAgentRunEventsQueryRequest, Result<AgentRunEventsDto>>
{
    /// <summary>Tek replay sayfasının üst sınırı; sınırsız akış üretilmez.</summary>
    public const int MaxPageSize = 200;

    /// <summary>Detail değerlerinin üst sınırı (güvenlik: ham log/istisna taşması
    /// riskine karşı değer başına kesme; anahtarlar agent_core küratörlüğündedir).</summary>
    public const int MaxDetailValueLength = 500;

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

        var replayQuery = dbContext.AgentEventInboxes
            .AsNoTracking()
            .Where(i => i.ConsumerName == AgentRunEventProjectionHandler.ConsumerName
                        && i.RunId == request.RunId
                        && i.Status == "applied"
                        && i.EventSequence > request.After)
            .OrderBy(i => i.EventSequence)
            .Take(pageSize)
            .Select(i => new ReplayRow
            {
                EventSequence = i.EventSequence,
                MessageType = i.MessageType,
                MessageId = i.MessageId.ToString("D"),
                OccurredAt = new DateTimeOffset(i.CreatedAt, TimeSpan.Zero),
                PayloadJson = i.PayloadJson,
                ProgressMessage = i.ProgressMessage,
            });
        var rows = await replayQuery.ToListAsync(cancellationToken);
        var settings = acceptanceOptions?.Value ?? new();

        // Replay can contain the full generated answer in progress bodies. Apply
        // the same current-source policy as terminal GET, including active runs.
        var presentation = await presentationGuard.CheckAsync(
            new AgentRunResultContext(run.Id, run.ArticleId, run.ResultJson, run.ContextSnapshotJson), cancellationToken);
        var stable = await AgentTerminalRecoveryPolicy.StabilizeExpiredAsync(dbContext.AgentRuns, run, settings, cancellationToken);
        if (!ReferenceEquals(stable, run))
        {
            run = stable;
            rows = await replayQuery.ToListAsync(cancellationToken);
            presentation = await presentationGuard.CheckAsync(
                new AgentRunResultContext(run.Id, run.ArticleId, run.ResultJson, run.ContextSnapshotJson), cancellationToken);
        }
        var suppressDeltaBodies = ShouldSuppressDeltaBodies(run.ContextSnapshotJson, run.SourceScope);
        var events = rows.Select(row => MapToEventDto(row, suppressDeltaBodies, !presentation.IsPresentable)).ToList();
        var recovery = AgentTerminalRecoveryPolicy.Evaluate(run, settings, DateTimeOffset.UtcNow);

        return Result<AgentRunEventsDto>.Success(new AgentRunEventsDto
        {
            RunId = run.Id,
            RunStatus = run.Status.ToString(),
            LastEventSequence = run.LastEventSequence,
            HasMore = events.Count == pageSize,
            IsProvisionalTerminal = recovery.IsProvisionalTerminal,
            ReconciliationUntil = recovery.ReconciliationUntil,
            ReconciliationRemainingSeconds = recovery.ReconciliationRemainingSeconds,
            Events = events,
        });
    }

    /// <summary>Sorgu projeksiyonu: inbox satırının replay'e giren alanları.
    /// API yüzeyine çıkmaz; yalnız türetme girdisidir.</summary>
    private sealed record ReplayRow
    {
        public long EventSequence { get; init; }

        public string MessageType { get; init; } = string.Empty;

        public string MessageId { get; init; } = string.Empty;

        public DateTimeOffset OccurredAt { get; init; }

        public string? PayloadJson { get; init; }

        public string? ProgressMessage { get; init; }
    }

    /// <summary>Ortak olay yüzeyi eşlemesi: mevcut dört alan birebir korunur;
    /// Kind/Message/Detail saklanan payload'dan türetilir.</summary>
    /// <summary>Profil run'ı: konu who_am_i (kabulde sabit) veya etkin kapsam profile
    /// (v2 mode_selected / terminal source_scope).</summary>
    public static bool ShouldSuppressDeltaBodies(string? contextSnapshotJson, string? runSourceScope) =>
        AgentRunWireContext.Parse(contextSnapshotJson).IsWhoAmI
        || string.Equals(runSourceScope, "profile", StringComparison.Ordinal);

    private static AgentRunEventDto MapToEventDto(ReplayRow row, bool suppressDeltaBodies, bool suppressAllBodies)
    {
        // Progressed: kind/message/detail payload'tan; diğer türlerde null.
        string? kind = null;
        string? message = null;
        IReadOnlyDictionary<string, string>? detail = null;

        if (string.Equals(row.MessageType, AgentMessageTypes.RunProgressed, StringComparison.Ordinal))
        {
            var payload = ParseProgressedPayload(row.PayloadJson);
            kind = payload?.Kind; // bozuk/eksik payload → null (olay düşmez)
            message = payload is null ? null : (row.ProgressMessage ?? payload.Message);
            detail = payload?.Detail is { } source
                ? source.ToDictionary(
                    pair => pair.Key,
                    pair => pair.Value is { Length: > MaxDetailValueLength }
                        ? pair.Value[..MaxDetailValueLength]
                        : pair.Value ?? string.Empty)
                : null;
        }
        else
        {
            // Terminal + action.proposed: messageType son ekinden türet (sözleşme).
            kind = DeriveSuffixKind(row.MessageType);
        }

        if (suppressAllBodies || (suppressDeltaBodies && kind == "generation_delta"))
        {
            message = null;
            detail = null;
        }

        return new AgentRunEventDto
        {
            EventSequence = row.EventSequence,
            MessageType = row.MessageType,
            MessageId = row.MessageId,
            OccurredAt = row.OccurredAt,
            Kind = kind,
            Message = message,
            Detail = detail,
        };
    }

    /// <summary>messageType son ekinden kind (terminal + action.proposed sözleşmesi).</summary>
    private static string? DeriveSuffixKind(string messageType)
    {
        var suffix = messageType[(messageType.LastIndexOf('.') + 1)..];
        return suffix switch
        {
            "completed" => "completed",
            "partially_completed" => "partial",
            "failed" => "failed",
            "cancelled" => "cancelled",
            "proposed" => "action_proposed",
            _ => null, // accepted / mode_selected / needs_input: sözleşmede kind yok
        };
    }

    /// <summary>Progressed payload'ını çözümler; bozuk/eksik JSON'da null döner —
    /// olay düşmez (replay sözleşmesi: alanlar null, istek 200).</summary>
    private static AgentRunProgressedV1? ParseProgressedPayload(string? payloadJson)
    {
        if (string.IsNullOrWhiteSpace(payloadJson))
        {
            return null;
        }

        try
        {
            return JsonSerializer.Deserialize<AgentRunProgressedV1>(payloadJson);
        }
        catch (JsonException)
        {
            return null;
        }
    }
}
