using System.Data;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using BlogApp.Core.Application.Common.Errors;
using BlogApp.Core.Application.Common.Interfaces.Data;
using BlogApp.Core.Application.Common.Interfaces.Messaging;
using BlogApp.Core.Application.Common.Interfaces.Persistence;
using BlogApp.Core.Application.Common.Interfaces.Services;
using BlogApp.Core.Application.Common.Messaging;
using BlogApp.Core.Application.Common.Models;
using BlogApp.Core.Application.Common.Options;
using BlogApp.Core.Domain.Entities;
using BlogApp.Core.Domain.Enums;
using MediatR;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;

namespace BlogApp.Core.Application.Features.AgentFeature.Commands.AcceptAgentRunCommand;

/// <summary>
/// Agent iş kabulü (plan satır 283-293). Sorumluluk zinciri:
/// 1. Oturum doğrulama — kimlik JWT'den (ICurrentUserService) veya sunucu tarafı misafir
///    oturumundan çözümlenir; istemcinin owner alanı yetki kaynağı değildir (plan satır 124).
/// 2. Makale erişimi — yalnız yayımlanmış makaleler sorulabilir; erişim kararı backend'dedir.
/// 3. Limit — sahip başına eşzamanlı (çözümlenmemiş) iş üst sınırı (K5).
/// 4. Idempotency — aynı anahtar + aynı payload → mevcut run geri döner; farklı payload → çakışma.
/// 5. run_id + turn_sequence + immutable bağlam snapshot'ı üretimi.
/// 6. AgentRun + OutboxMessage TEK transaction'da; zarf commit öncesi B1 sözleşme doğrulayıcısından
///    geçer — rollback durumunda hayalet komut oluşmaz (kabul ölçütü, satır 307).
/// 7. Commit sonrası accepted run_id döner. Kabul durumu ile Python'ın accepted olayı AYRI
///    anlamlardır (satır 305).
/// </summary>
public sealed class AcceptAgentRunCommandHandler(
    IUnitOfWork unitOfWork,
    IApplicationDbContext dbContext,
    ICurrentUserService currentUser,
    IOutboxWriter outboxWriter,
    IOptions<AgentAcceptanceSettings> acceptanceOptions,
    IOptions<AgentMessagingSettings> messagingOptions,
    ILogger<AcceptAgentRunCommandHandler> logger) : IRequestHandler<AcceptAgentRunCommandRequest, Result<AgentRunAcceptedDto>>
{
    public async Task<Result<AgentRunAcceptedDto>> Handle(AcceptAgentRunCommandRequest request, CancellationToken cancellationToken)
    {
        var settings = acceptanceOptions.Value;

        // 1) Oturum doğrulama: JWT kimliği önceliklidir; misafir yalnız sunucu üretiği oturumla gelir.
        var userId = currentUser.UserId;
        var guestSessionId = request.GuestSessionId?.Trim();
        if (userId is null && string.IsNullOrWhiteSpace(guestSessionId))
        {
            return Result<AgentRunAcceptedDto>.Failure(Error.Unauthorized("Agent işi için oturum gereklidir."));
        }

        if (userId is null && !settings.AllowGuestRuns)
        {
            return Result<AgentRunAcceptedDto>.Failure(Error.Forbidden("Misafir agent işi kabulü kapalıdır."));
        }

        var ownerKey = userId is not null ? $"u:{userId.Value:D}" : $"g:{guestSessionId}";

        // 2) Makale erişimi: yalnız yayımlanmış makale kabul edilir (silinmişler query filter ile dışarıda).
        BlogPost? article = null;
        if (request.ArticleId is { } articleId)
        {
            article = await dbContext.Posts
                .AsNoTracking()
                .FirstOrDefaultAsync(p => p.Id == articleId, cancellationToken);
            if (article is null)
            {
                return Result<AgentRunAcceptedDto>.Failure(Error.NotFound("Makale bulunamadı."));
            }

            if (article.Status != PostStatus.Published)
            {
                return Result<AgentRunAcceptedDto>.Failure(Error.Forbidden("Makale şu an agent sorularına açık değil."));
            }
        }

        var payloadHash = ComputePayloadHash(request);
        var occurredAt = DateTimeOffset.UtcNow;
        var conversationId = request.ConversationId ?? Guid.NewGuid();
        var correlationId = Guid.NewGuid().ToString("D");

        // 6) Tek transaction: idempotency, limit, run + outbox yazımı.
        try
        {
            return await unitOfWork.ExecuteResilientAsync(async ct =>
            {
                await using var transaction = await unitOfWork.BeginTransactionAsync(IsolationLevel.ReadCommitted, ct);

                // 4a) Tekrarlı kabul: aynı anahtar → payload özeti karşılaştırılır.
                var existing = await dbContext.AgentRuns
                    .AsNoTracking()
                    .FirstOrDefaultAsync(r => r.OwnerKey == ownerKey && r.IdempotencyKey == request.IdempotencyKey, ct);
                if (existing is not null)
                {
                    if (existing.IdempotencyPayloadHash != payloadHash)
                    {
                        return Result<AgentRunAcceptedDto>.Failure(Error.Conflict(
                            "Bu idempotency anahtarı farklı bir istek için kullanılmış."));
                    }

                    logger.LogInformation(
                        "[AgentAccept] idempotent replay: run {RunId} key {Key}", existing.Id, request.IdempotencyKey);
                    return Result<AgentRunAcceptedDto>.Success(new AgentRunAcceptedDto(
                        existing.Id,
                        existing.ConversationId,
                        existing.TurnSequence,
                        existing.AcceptedAt,
                        existing.DeadlineAt,
                        Replay: true));
                }

                // 4b) Konuşma sahipliği: mevcut konuşma başka sahibe aitse kabul edilmez.
                var foreignConversation = await dbContext.AgentRuns
                    .AsNoTracking()
                    .AnyAsync(r => r.ConversationId == conversationId && r.OwnerKey != ownerKey, ct);
                if (foreignConversation)
                {
                    return Result<AgentRunAcceptedDto>.Failure(Error.Forbidden("Konuşma başka bir oturuma ait."));
                }

                // 3) Limit: sahip başına eşzamanlı (çözümlenmemiş) iş üst sınırı
                //    + sistem düzeyi kapasite sınırı (B7 backpressure).
                var activeRuns = await dbContext.AgentRuns
                    .AsNoTracking()
                    .CountAsync(r => r.OwnerKey == ownerKey && r.Status == AgentRunStatus.Accepted, ct);
                if (activeRuns >= settings.MaxActiveRunsPerOwner)
                {
                    return Result<AgentRunAcceptedDto>.Failure(Error.Domain(
                        $"Eşzamanlı agent iş sınırına ulaşıldı ({settings.MaxActiveRunsPerOwner}). Devam eden işler bitmeden yeni iş kabul edilmez."));
                }

                var activeTotal = await dbContext.AgentRuns
                    .AsNoTracking()
                    .CountAsync(r => r.Status == AgentRunStatus.Accepted, ct);
                if (activeTotal >= settings.MaxActiveRunsTotal)
                {
                    return Result<AgentRunAcceptedDto>.Failure(Error.Domain(
                        $"Sistem agent kapasitesi dolu ({settings.MaxActiveRunsTotal}). Lütfen kısa süre sonra tekrar deneyin."));
                }

                // 5) turn_sequence: konuşma içinde monoton; (ConversationId, TurnSequence) unique ile korunur.
                var lastTurn = await dbContext.AgentRuns
                    .AsNoTracking()
                    .Where(r => r.ConversationId == conversationId)
                    .MaxAsync(r => (long?)r.TurnSequence, ct);
                var turnSequence = (lastTurn ?? 0) + 1;

                var runId = Guid.NewGuid();
                var deadlineAt = occurredAt.AddMinutes(DeadlineMinutesFor(settings, request.ModePreference));
                var (snapshotJson, contentHash, snapshotReference, articleRevision) =
                    BuildContextSnapshot(runId, turnSequence, request, article);

                // 5) Immutable zarf üretimi ve commit öncesi sözleşme doğrulaması.
                //    Makale bağlamı üçlü halinde taşınır (B1 all-or-none; W5 bulgusu 4i):
                //    worker stale komut guard'ı (B8) bu üçlüyle çalışır.
                var userRef = userId is not null ? $"u:{userId.Value:D}" : $"g:{guestSessionId}";
                var (envelopeJson, messageId) = AgentCommandEnvelopeComposer.ComposeExecutionRequested(
                    runId,
                    conversationId,
                    correlationId,
                    occurredAt,
                    deadlineAt,
                    producer: messagingOptions.Value.ProducerName,
                    userRef: userRef,
                    question: request.Question,
                    language: request.Language,
                    modePreference: request.ModePreference,
                    budgetProfile: request.BudgetProfile,
                    contextSnapshotReference: snapshotReference,
                    selectedText: request.SelectedText,
                    articleId: article?.Id.ToString("D"),
                    articleRevision: articleRevision,
                    articleContentHash: article is null ? null : contentHash);

                var contractResult = new AgentContractValidator(messagingOptions.Value).Validate(envelopeJson);
                if (!contractResult.IsValid)
                {
                    logger.LogWarning(
                        "[AgentAccept] zarf sözleşme doğrulaması reddetti: {Field} {Detail}",
                        contractResult.Error!.Field, contractResult.Error.Message);
                    return Result<AgentRunAcceptedDto>.Failure(Error.Domain(
                        "İş komutu sözleşme doğrulamasını geçemedi; iş kabul edilmedi."));
                }

                var run = new AgentRun
                {
                    Id = runId,
                    ConversationId = conversationId,
                    TurnSequence = turnSequence,
                    OwnerKey = ownerKey,
                    OwnerUserId = userId,
                    GuestSessionId = userId is null ? guestSessionId : null,
                    IdempotencyKey = request.IdempotencyKey,
                    IdempotencyPayloadHash = payloadHash,
                    Status = AgentRunStatus.Accepted,
                    Question = request.Question,
                    Language = request.Language,
                    ModePreference = request.ModePreference,
                    BudgetProfile = request.BudgetProfile,
                    ArticleId = article?.Id,
                    ArticleContentHash = contentHash,
                    ContextSnapshotReference = snapshotReference,
                    ContextSnapshotJson = snapshotJson,
                    DeadlineAt = deadlineAt.UtcDateTime,
                    AcceptedAt = occurredAt.UtcDateTime,
                };

                var outboxMessage = new OutboxMessage
                {
                    MessageId = messageId,
                    MessageType = AgentMessageTypes.ExecutionRequested,
                    Exchange = AgentMessageTypeRegistry.CommandsExchange,
                    RoutingKey = "agent.execute.requested.v1",
                    CorrelationId = correlationId,
                    RunId = runId,
                    EnvelopeJson = envelopeJson,
                    Status = AgentOutboxStatus.Pending,
                };

                await dbContext.AgentRuns.AddAsync(run, ct);
                await outboxWriter.AddAsync(outboxMessage, ct);
                await unitOfWork.SaveChangesAsync(ct);
                await transaction.CommitAsync(ct);

                logger.LogInformation(
                    "[AgentAccept] run {RunId} accepted (turn {Turn}, outbox {MessageId})",
                    runId, turnSequence, messageId);

                return Result<AgentRunAcceptedDto>.Success(new AgentRunAcceptedDto(
                    runId,
                    conversationId,
                    turnSequence,
                    run.AcceptedAt,
                    run.DeadlineAt,
                    Replay: false));
            }, cancellationToken);
        }
        catch (DbUpdateException exception)
        {
            // Benzersizlik yarışları: (OwnerKey, IdempotencyKey) veya (ConversationId, TurnSequence).
            var existing = await dbContext.AgentRuns
                .AsNoTracking()
                .FirstOrDefaultAsync(r => r.OwnerKey == ownerKey && r.IdempotencyKey == request.IdempotencyKey, cancellationToken);
            if (existing is not null)
            {
                return existing.IdempotencyPayloadHash == payloadHash
                    ? Result<AgentRunAcceptedDto>.Success(new AgentRunAcceptedDto(
                        existing.Id, existing.ConversationId, existing.TurnSequence,
                        existing.AcceptedAt, existing.DeadlineAt, Replay: true))
                    : Result<AgentRunAcceptedDto>.Failure(Error.Conflict(
                        "Bu idempotency anahtarı farklı bir istek için kullanılmış."));
            }

            logger.LogWarning(exception, "[AgentAccept] eşzamanlı kabul çakışması (conversation {ConversationId})", conversationId);
            return Result<AgentRunAcceptedDto>.Failure(Error.Conflict(
                "Aynı konuşmada eşzamanlı istek çakışması; isteği tekrarlayın."));
        }
    }

    private static int DeadlineMinutesFor(AgentAcceptanceSettings settings, string modePreference) =>
        modePreference switch
        {
            "fast" => settings.FastDeadlineMinutes,
            "analysis" => settings.AnalysisDeadlineMinutes,
            "deep_research" => settings.DeepResearchDeadlineMinutes,
            _ => settings.AutoDeadlineMinutes,
        };

    /// <summary>Immutable bağlam snapshot'ı: kabul anındaki makale özeti + soru bağlamı (K7:
    /// içerik mesaja gömülmez; snapshot hash referansı taşır). content_hash = UTF-8 SHA-256 (D008);
    /// BlogPost.Version kullanılmaz (L004). article_revision kabul anındaki backend-atandı
    /// monoton yayımlanmış içerik anıdır (BlogPost.ContentRevision); komut üçlüsünün
    /// article_revision kaynağı budur (W5 bulgusu 4i).</summary>
    private static (string SnapshotJson, string? ContentHash, string SnapshotReference, long? ArticleRevision)
        BuildContextSnapshot(Guid runId, long turnSequence, AcceptAgentRunCommandRequest request, BlogPost? article)
    {
        string? contentHash = null;
        string? publishedAt = null;
        long? articleRevision = null;
        if (article is not null)
        {
            contentHash = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(article.Content))).ToLowerInvariant();
            publishedAt = article.PublishedAt is { } published
                ? AgentCommandEnvelopeComposer.FormatUtc(new DateTimeOffset(published, TimeSpan.Zero))
                : null;
            articleRevision = article.ContentRevision;
        }

        var snapshot = new Dictionary<string, string?>
        {
            ["article_id"] = article?.Id.ToString("D"),
            ["title"] = article?.Title,
            ["slug"] = article?.Slug,
            ["content_hash"] = contentHash,
            ["article_revision"] = articleRevision?.ToString(System.Globalization.CultureInfo.InvariantCulture),
            ["published_at"] = publishedAt,
            ["question"] = request.Question,
            ["language"] = request.Language,
            ["mode_preference"] = request.ModePreference,
            ["selected_text"] = request.SelectedText,
        };

        var snapshotJson = JsonSerializer.Serialize(snapshot, AgentCommandEnvelopeComposer.SerializerOptions);
        var snapshotReference = $"agent-run/{runId:D}/turn/{turnSequence}";
        return (snapshotJson, contentHash, snapshotReference, articleRevision);
    }

    private static string ComputePayloadHash(AcceptAgentRunCommandRequest request)
    {
        var canonical = string.Join('\n',
            request.Question,
            request.Language,
            request.ModePreference,
            request.BudgetProfile,
            request.ArticleId?.ToString("D") ?? string.Empty,
            request.SelectedText ?? string.Empty);
        return Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(canonical))).ToLowerInvariant();
    }
}
