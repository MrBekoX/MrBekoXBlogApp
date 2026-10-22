using System.Data;
using System.Globalization;
using System.Text.Json;
using BlogApp.Core.Application.Common.AuthorProfile;
using BlogApp.Core.Application.Common.Errors;
using BlogApp.Core.Application.Common.Interfaces.Data;
using BlogApp.Core.Application.Common.Interfaces.Messaging;
using BlogApp.Core.Application.Common.Interfaces.Persistence;
using BlogApp.Core.Application.Common.Interfaces.Services;
using BlogApp.Core.Application.Common.Messaging;
using BlogApp.Core.Application.Common.Models;
using BlogApp.Core.Application.Common.Options;
using BlogApp.Core.Application.Features.AgentFeature.Services;
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
///    who_am_i konusu özete girer (A28).
/// 5. run_id + turn_sequence + immutable bağlam snapshot'ı üretimi (wire sürümü, konu ve pinlenmiş
///    profil snapshot'ı dahil; K6).
/// 6. AgentRun + OutboxMessage TEK transaction'da; zarf commit öncesi sözleşme doğrulayıcısından
///    geçer — rollback durumunda hayalet komut oluşmaz (kabul ölçütü, satır 307).
/// 7. Commit sonrası accepted run_id döner. Kabul durumu ile Python'ın accepted olayı AYRI
///    anlamlardır (satır 305).
/// Wire sürümü (K4): <see cref="IAgentWireVersionSelector"/> v2'yi yalnız AgentWireV2 açık ve broker
/// bariyeri hazırken seçer; aksi halde auto → v1 (eski akış birebir), who_am_i → 503
/// capability_unavailable (modele sessiz düşüş yok). v2 run'da profil hazırsa snapshot pinlenir;
/// değilse auto için profile_capability=unavailable kaydedilir, who_am_i 503 alır.
/// Opsiyonel bağımlılıklar verilmezse (eski test kurulumları) davranış v1 ile birebir aynıdır.
/// </summary>
public sealed class AcceptAgentRunCommandHandler(
    IUnitOfWork unitOfWork,
    IApplicationDbContext dbContext,
    ICurrentUserService currentUser,
    IOutboxWriter outboxWriter,
    IOptions<AgentAcceptanceSettings> acceptanceOptions,
    IOptions<AgentMessagingSettings> messagingOptions,
    ILogger<AcceptAgentRunCommandHandler> logger,
    IAgentWireVersionSelector? wireVersionSelector = null,
    IAuthorProfileSource? profileSource = null,
    IAgentConversationHistoryComposer? historyComposer = null) : IRequestHandler<AcceptAgentRunCommandRequest, Result<AgentRunAcceptedDto>>
{
    public const string WhoAmIDisabledMessage =
        "Who am I konusu şu an kullanılamıyor (özellik kapalı veya agent hazır değil). Lütfen daha sonra tekrar deneyin ya da Otomatik konuyu kullanın.";

    public const string ProfileUnavailableMessage =
        "Who am I konusu şu an kullanılamıyor: onaylı profil kaynağı doğrulanamadı. Lütfen daha sonra tekrar deneyin.";

    public const string ConversationTopicChangedMessage =
        "Bu sohbet farklı bir konuyla başladı; konu değiştiğinde yeni bir sohbet başlatın (conversationId göndermeyin).";

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

        // Konu (K1/K6): doğrulayıcı pipeline'da çalışır; handler doğrudan çağrıldığında da
        // who_am_i ile uyumsuz istemci alanları açıklamalı validation_error alır.
        var topic = AgentConversationTopics.Normalize(request.ConversationTopic);
        var topicError = ValidateTopic(request, topic);
        if (topicError is not null)
        {
            return Result<AgentRunAcceptedDto>.Failure(topicError);
        }

        var isWhoAmI = topic == AgentConversationTopics.WhoAmI;

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

        // Wire sürümü + profil pini (K4/K6). Kapasite hatası idempotent replay'den SONRA döner:
        // önceden kabul edilmiş aynı istek, anahtar kapatılsa bile mevcut run'ı geri alır.
        var wireVersion = wireVersionSelector is null
            ? AgentMessageTypeRegistry.V1
            : await wireVersionSelector.SelectAsync(cancellationToken);
        AuthorProfileSnapshot? pinnedProfile = null;
        string? profileCapability = null;
        Error? capabilityError = null;
        if (wireVersion >= AgentMessageTypeRegistry.V2)
        {
            var profileState = profileSource?.GetCurrent();
            if (profileState is { IsAvailable: true })
            {
                pinnedProfile = profileState.ActiveSnapshot;
                profileCapability = AgentRunContextKeys.CapabilityAvailable;
            }
            else
            {
                profileCapability = AgentRunContextKeys.CapabilityUnavailable;
                if (isWhoAmI)
                {
                    capabilityError = Error.Unavailable(ProfileUnavailableMessage);
                }
            }
        }
        else if (isWhoAmI)
        {
            capabilityError = Error.Unavailable(WhoAmIDisabledMessage);
        }

        var payloadHash = AgentRunIdempotencyHash.Compute(request, topic);
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
                    return Result<AgentRunAcceptedDto>.Success(ReplayDto(existing));
                }

                // 4b) Konuşma sahipliği: mevcut konuşma başka sahibe aitse kabul edilmez.
                var foreignConversation = await dbContext.AgentRuns
                    .AsNoTracking()
                    .AnyAsync(r => r.ConversationId == conversationId && r.OwnerKey != ownerKey, ct);
                if (foreignConversation)
                {
                    return Result<AgentRunAcceptedDto>.Failure(Error.Forbidden("Konuşma başka bir oturuma ait."));
                }

                // 4c) Konu sohbet için sabittir (K6): farklı konulu önceki run'ı olan konuşma reddedilir.
                var previousContext = await dbContext.AgentRuns
                    .AsNoTracking()
                    .Where(r => r.ConversationId == conversationId)
                    .OrderByDescending(r => r.TurnSequence)
                    .Select(r => r.ContextSnapshotJson)
                    .FirstOrDefaultAsync(ct);
                if (!AgentConversationTopicRules.IsCompatible(previousContext, topic))
                {
                    return Result<AgentRunAcceptedDto>.Failure(Error.Validation(new Dictionary<string, string[]>
                    {
                        ["ConversationTopic"] = [ConversationTopicChangedMessage],
                    }));
                }

                if (capabilityError is not null)
                {
                    logger.LogInformation(
                        "[AgentAccept] who_am_i kapasitesi kullanılamıyor (wire v{Wire}); iş kabul edilmedi", wireVersion);
                    return Result<AgentRunAcceptedDto>.Failure(capabilityError);
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

                // v2: aynı sahip + konuşma + konu için sunum denetiminden geçen tamamlanmış turlar (K6).
                IReadOnlyList<AgentConversationTurn> history = [];
                if (wireVersion >= AgentMessageTypeRegistry.V2 && historyComposer is not null && lastTurn is not null)
                {
                    history = await historyComposer.ComposeAsync(ownerKey, conversationId, topic, ct);
                }

                var runId = Guid.NewGuid();
                var deadlineAt = occurredAt.AddMinutes(DeadlineMinutesFor(settings, request.ModePreference));
                var (snapshotJson, contentHash, snapshotReference, articleRevision) = BuildContextSnapshot(
                    runId, turnSequence, request, article, wireVersion, topic, pinnedProfile, profileCapability);

                // 5) Immutable zarf üretimi ve commit öncesi sözleşme doğrulaması.
                //    Makale bağlamı üçlü halinde taşınır (B1 all-or-none; W5 bulgusu 4i):
                //    worker stale komut guard'ı (B8) bu üçlüyle çalışır. v2'de geçmiş zarf üst
                //    sınırını aşarsa en eski soru/cevap çiftlerinden kırpılır.
                var userRef = userId is not null ? $"u:{userId.Value:D}" : $"g:{guestSessionId}";
                var validator = new AgentContractValidator(messagingOptions.Value);
                string envelopeJson;
                string messageId;
                AgentContractValidationResult contractResult;
                while (true)
                {
                    (envelopeJson, messageId) = AgentCommandEnvelopeComposer.ComposeExecutionRequested(
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
                        articleContentHash: article is null ? null : contentHash,
                        schemaVersion: wireVersion,
                        conversationTopic: wireVersion >= AgentMessageTypeRegistry.V2 ? topic : null,
                        profileSnapshot: wireVersion >= AgentMessageTypeRegistry.V2 ? pinnedProfile?.ToRef() : null,
                        conversationHistory: wireVersion >= AgentMessageTypeRegistry.V2 ? history : null);

                    contractResult = validator.Validate(envelopeJson);
                    if (!contractResult.IsValid
                        && contractResult.Error!.Category == AgentContractErrorCategory.Oversized
                        && history.Count > 0)
                    {
                        history = history.Skip(Math.Min(2, history.Count)).ToList();
                        continue;
                    }

                    break;
                }

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
                    RoutingKey = AgentMessageTypeRegistry.RoutingKeyFor(wireVersion, AgentMessageTypes.ExecutionRequested),
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
                    "[AgentAccept] run {RunId} accepted (turn {Turn}, wire v{Wire}, topic {Topic}, outbox {MessageId})",
                    runId, turnSequence, wireVersion, topic, messageId);

                return Result<AgentRunAcceptedDto>.Success(new AgentRunAcceptedDto(
                    runId,
                    conversationId,
                    turnSequence,
                    run.AcceptedAt,
                    run.DeadlineAt,
                    Replay: false,
                    ConversationTopic: topic,
                    WireVersion: wireVersion));
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
                    ? Result<AgentRunAcceptedDto>.Success(ReplayDto(existing))
                    : Result<AgentRunAcceptedDto>.Failure(Error.Conflict(
                        "Bu idempotency anahtarı farklı bir istek için kullanılmış."));
            }

            logger.LogWarning(exception, "[AgentAccept] eşzamanlı kabul çakışması (conversation {ConversationId})", conversationId);
            return Result<AgentRunAcceptedDto>.Failure(Error.Conflict(
                "Aynı konuşmada eşzamanlı istek çakışması; isteği tekrarlayın."));
        }
    }

    /// <summary>who_am_i ile uyumsuz istemci alanları (doğrulayıcıyla aynı kurallar; handler doğrudan
    /// çağrıldığında da uygulanır).</summary>
    private static Error? ValidateTopic(AcceptAgentRunCommandRequest request, string topic)
    {
        if (!AgentConversationTopics.IsKnown(topic))
        {
            return Error.Validation(new Dictionary<string, string[]>
            {
                ["ConversationTopic"] = ["conversationTopic auto veya who_am_i olmalıdır."],
            });
        }

        if (topic != AgentConversationTopics.WhoAmI)
        {
            return null;
        }

        var errors = new Dictionary<string, string[]>();
        if (request.ArticleId is not null)
        {
            errors["ArticleId"] = [AcceptAgentRunCommandValidator.WhoAmIArticleMessage];
        }

        if (!string.IsNullOrWhiteSpace(request.SelectedText))
        {
            errors["SelectedText"] = [AcceptAgentRunCommandValidator.WhoAmISelectedTextMessage];
        }

        if (request.IsResearchRequest)
        {
            errors["IsResearchRequest"] = [AcceptAgentRunCommandValidator.WhoAmIResearchMessage];
        }

        return errors.Count == 0 ? null : Error.Validation(errors);
    }

    private static AgentRunAcceptedDto ReplayDto(AgentRun existing)
    {
        var wire = AgentRunWireContext.Parse(existing.ContextSnapshotJson);
        return new AgentRunAcceptedDto(
            existing.Id,
            existing.ConversationId,
            existing.TurnSequence,
            existing.AcceptedAt,
            existing.DeadlineAt,
            Replay: true,
            ConversationTopic: wire.ConversationTopic,
            WireVersion: wire.WireVersion);
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
    /// article_revision kaynağı budur (W5 bulgusu 4i). K6 anahtarları: wire_version,
    /// conversation_topic ve (v2) profile_id/profile_revision/profile_content_hash/profile_capability —
    /// profil GÖVDESİ saklanmaz, yalnız pinlenen sürüm referansı.</summary>
    public static (string SnapshotJson, string? ContentHash, string SnapshotReference, long? ArticleRevision)
        BuildContextSnapshot(
            Guid runId,
            long turnSequence,
            AcceptAgentRunCommandRequest request,
            BlogPost? article,
            int wireVersion = AgentMessageTypeRegistry.V1,
            string conversationTopic = AgentConversationTopics.Auto,
            AuthorProfileSnapshot? pinnedProfile = null,
            string? profileCapability = null)
    {
        string? contentHash = null;
        string? publishedAt = null;
        long? articleRevision = null;
        if (article is not null)
        {
            contentHash = AgentArticleContentHash.Compute(article.Content);
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
            ["article_revision"] = articleRevision?.ToString(CultureInfo.InvariantCulture),
            ["published_at"] = publishedAt,
            ["question"] = request.Question,
            ["language"] = request.Language,
            ["mode_preference"] = request.ModePreference,
            ["selected_text"] = request.SelectedText,
            [AgentRunContextKeys.WireVersion] = wireVersion.ToString(CultureInfo.InvariantCulture),
            [AgentRunContextKeys.ConversationTopic] = conversationTopic,
            [AgentRunContextKeys.ProfileId] = pinnedProfile?.ProfileId,
            [AgentRunContextKeys.ProfileRevision] = pinnedProfile?.Revision.ToString(CultureInfo.InvariantCulture),
            [AgentRunContextKeys.ProfileContentHash] = pinnedProfile?.ContentHash,
            [AgentRunContextKeys.ProfileCapability] = profileCapability,
        };

        var snapshotJson = JsonSerializer.Serialize(snapshot, AgentCommandEnvelopeComposer.SerializerOptions);
        var snapshotReference = $"agent-run/{runId:D}/turn/{turnSequence}";
        return (snapshotJson, contentHash, snapshotReference, articleRevision);
    }
}

/// <summary>Konu sabitliği kuralı (K6): konuşmanın önceki run'ının konusu (eksikse auto) istenen
/// konuyla aynı olmalıdır; ilk tur her konuyla başlayabilir.</summary>
public static class AgentConversationTopicRules
{
    public static bool IsCompatible(string? previousContextSnapshotJson, string requestedTopic) =>
        previousContextSnapshotJson is null
        || AgentRunWireContext.Parse(previousContextSnapshotJson).ConversationTopic == requestedTopic;
}
