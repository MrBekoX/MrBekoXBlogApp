using System.Security.Cryptography;
using BlogApp.Core.Application.Common.Errors;
using BlogApp.Core.Application.Common.Interfaces.Data;
using BlogApp.Core.Application.Common.Interfaces.Persistence;
using BlogApp.Core.Application.Common.Interfaces.Services;
using BlogApp.Core.Application.Common.Models;
using BlogApp.Core.Domain.Entities;
using MediatR;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging;

namespace BlogApp.Core.Application.Features.AgentFeature.Commands.RecordAgentFeedbackCommand;

/// <summary>
/// Agent geri bildirim kaydı port'u (B10). Depolama B10'da MEVCUT projection
/// tablosuyla (agent_event_inboxes) yapılır: plan B10 admin listesi geri bildirim
/// özetlerini "mevcut projection/outbox tablolarından okuma" ile ister ve yeni
/// migration sahipliği bu faza ait değildir. Kayıt ``backend-agent-feedback``
/// tüketici adıyla, (runId, feedback_key)'ten türetilmiş mesaj kimliğiyle ve
/// ``agent.feedback.recorded`` tür adıyla yazılır; PK (ConsumerName, MessageId)
/// ikili gönderimi tek kayda indirger (çift tık/ağ tekrarı tek kayıt).
/// B9/B11 ayrı bir tabloya taşırsa yalnız bu port'un uygulaması değişir.
/// </summary>
public sealed record AgentFeedbackRecord
{
    public required Guid RunId { get; init; }

    /// <summary>İstemcinin ürettiği tek kullanımlık anahtar; kimlik buradan türetilir.</summary>
    public required string FeedbackKey { get; init; }

    public required int Rating { get; init; }

    public string? Comment { get; init; }
}

public interface IAgentFeedbackStore
{
    /// <summary>Aynı (run, anahtar) kaydı zaten varsa true (replay kararı).</summary>
    Task<bool> ExistsAsync(Guid runId, string feedbackKey, CancellationToken cancellationToken = default);

    Task WriteAsync(AgentFeedbackRecord record, CancellationToken cancellationToken = default);
}

/// <summary>agent_event_inboxes tabanlı B10 uygulaması (bkz. <see cref="IAgentFeedbackStore"/>).</summary>
public sealed class ProjectionAgentFeedbackStore(IApplicationDbContext dbContext) : IAgentFeedbackStore
{
    public const string ConsumerName = "backend-agent-feedback";
    public const string MessageType = "agent.feedback.recorded";

    public Task<bool> ExistsAsync(Guid runId, string feedbackKey, CancellationToken cancellationToken = default) =>
        dbContext.AgentEventInboxes
            .AsNoTracking()
            .AnyAsync(i => i.ConsumerName == ConsumerName
                           && i.MessageId == DeriveMessageId(runId, feedbackKey), cancellationToken);

    public async Task WriteAsync(AgentFeedbackRecord record, CancellationToken cancellationToken = default)
    {
        var detail = System.Text.Json.JsonSerializer.Serialize(new Dictionary<string, string?>
        {
            ["rating"] = record.Rating.ToString(System.Globalization.CultureInfo.InvariantCulture),
            ["comment"] = record.Comment,
        });

        await dbContext.AgentEventInboxes.AddAsync(new AgentEventInbox
        {
            ConsumerName = ConsumerName,
            MessageId = DeriveMessageId(record.RunId, record.FeedbackKey),
            MessageType = MessageType,
            RunId = record.RunId,
            EventSequence = 0,
            Status = "applied",
            Detail = detail,
            CreatedAt = DateTime.UtcNow,
        }, cancellationToken);
    }

    /// <summary>Deterministik kimlik: aynı (run, anahtar) her zaman aynı satıra eşlenir;
    /// farklı anahtarlar çakışmaz (SHA-256 ilk 16 baytı).</summary>
    internal static Guid DeriveMessageId(Guid runId, string feedbackKey) =>
        new(SHA256.HashData(System.Text.Encoding.UTF8.GetBytes($"feedback:{runId:D}:{feedbackKey}")).Take(16).ToArray());
}

/// <summary>
/// Agent run'ına kullanıcı geri bildirimi kaydı (B10 endpoint'i; plan tablosu:
/// "Run sahipliğiyle geri bildirim kaydı"). Sahiplik cancel/resume deseninde
/// backend'de doğrulanır; kayıt idempotenttir (aynı feedback_key ile ikinci istek
/// yeni kayıt üretmez). Puanlama aralığı ve yorum uzunluğu doğrulanır; kişisel
/// veri taşınmaz (yalnız run + puan + yorum).
/// </summary>
public sealed class RecordAgentFeedbackCommandHandler(
    IUnitOfWork unitOfWork,
    IApplicationDbContext dbContext,
    ICurrentUserService currentUser,
    IAgentFeedbackStore feedbackStore,
    ILogger<RecordAgentFeedbackCommandHandler> logger) : IRequestHandler<RecordAgentFeedbackCommandRequest, Result<AgentFeedbackDto>>
{
    public async Task<Result<AgentFeedbackDto>> Handle(RecordAgentFeedbackCommandRequest request, CancellationToken cancellationToken)
    {
        if (request.Rating is < 1 or > 5)
        {
            return Result<AgentFeedbackDto>.Failure(Error.Validation("Puan 1-5 arasında olmalıdır."));
        }

        var comment = request.Comment?.Trim();
        if (comment is { Length: > 2000 })
        {
            return Result<AgentFeedbackDto>.Failure(Error.Validation("Yorum en fazla 2000 karakter olabilir."));
        }

        var feedbackKey = request.FeedbackKey?.Trim();
        if (string.IsNullOrWhiteSpace(feedbackKey) || feedbackKey.Length > 128)
        {
            return Result<AgentFeedbackDto>.Failure(Error.Validation("feedback_key zorunludur (en fazla 128 karakter)."));
        }

        // Oturum + sahiplik: run backend kaydına göre doğrulanır.
        var userId = currentUser.UserId;
        var guestSessionId = request.GuestSessionId?.Trim();
        if (userId is null && string.IsNullOrWhiteSpace(guestSessionId))
        {
            return Result<AgentFeedbackDto>.Failure(Error.Unauthorized("Agent işi için oturum gereklidir."));
        }

        var ownerKey = userId is not null ? $"u:{userId.Value:D}" : $"g:{guestSessionId}";

        var run = await dbContext.AgentRuns
            .AsNoTracking()
            .FirstOrDefaultAsync(r => r.Id == request.RunId, cancellationToken);
        if (run is null)
        {
            return Result<AgentFeedbackDto>.Failure(Error.NotFound("Agent işi bulunamadı."));
        }

        if (!string.Equals(run.OwnerKey, ownerKey, StringComparison.Ordinal))
        {
            return Result<AgentFeedbackDto>.Failure(Error.Forbidden("Bu agent işi başka bir oturuma ait."));
        }

        // İdempotent kayıt: aynı anahtar için mevcut kayıt replay yanıtı verir.
        var recorded = DateTimeOffset.UtcNow;
        if (await feedbackStore.ExistsAsync(request.RunId, feedbackKey, cancellationToken))
        {
            logger.LogInformation(
                "[AgentFeedback] run {RunId} için feedback anahtarı zaten kayıtlı; replay yanıtı",
                request.RunId);
            return Result<AgentFeedbackDto>.Success(new AgentFeedbackDto(request.RunId, "replay", recorded));
        }

        try
        {
            return await unitOfWork.ExecuteResilientAsync(async ct =>
            {
                await using var transaction = await unitOfWork.BeginTransactionAsync(
                    System.Data.IsolationLevel.ReadCommitted, ct);

                // Transaction içi ikinci kontrol: eşzamanlı ikiz istek tek kayda iner.
                if (await feedbackStore.ExistsAsync(request.RunId, feedbackKey, ct))
                {
                    await transaction.RollbackAsync(ct);
                    return Result<AgentFeedbackDto>.Success(new AgentFeedbackDto(request.RunId, "replay", recorded));
                }

                await feedbackStore.WriteAsync(new AgentFeedbackRecord
                {
                    RunId = request.RunId,
                    FeedbackKey = feedbackKey,
                    Rating = request.Rating,
                    Comment = string.IsNullOrEmpty(comment) ? null : comment,
                }, ct);
                await unitOfWork.SaveChangesAsync(ct);
                await transaction.CommitAsync(ct);

                logger.LogInformation(
                    "[AgentFeedback] run {RunId} için geri bildirim kaydedildi (rating {Rating})",
                    request.RunId, request.Rating);

                return Result<AgentFeedbackDto>.Success(new AgentFeedbackDto(request.RunId, "recorded", recorded));
            }, cancellationToken);
        }
        catch (DbUpdateException exception)
        {
            logger.LogWarning(exception, "[AgentFeedback] geri bildirim yazımı başarısız (run {RunId})", request.RunId);
            return Result<AgentFeedbackDto>.Failure(Error.Conflict(
                "Geri bildirim kaydedilemedi; isteği tekrarlayın."));
        }
    }
}
