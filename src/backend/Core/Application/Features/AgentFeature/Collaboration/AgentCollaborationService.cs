using System.Data;
using BlogApp.Core.Application.Common.Interfaces.Data;
using BlogApp.Core.Application.Common.Interfaces.Messaging;
using BlogApp.Core.Application.Common.Interfaces.Persistence;
using BlogApp.Core.Application.Common.Messaging;
using BlogApp.Core.Application.Common.Options;
using BlogApp.Core.Domain.Entities;
using BlogApp.Core.Domain.Enums;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;

namespace BlogApp.Core.Application.Features.AgentFeature.Collaboration;

/// <summary>
/// İş birliği onay ve resume sözleşmesi (B9; entegrasyon sahibi tanımı). Plan B9
/// davranışlarının backend yarısı:
///
/// <para><b>UpsertProposalAsync</b> — B5 projection'ı AgentActionProposedV1 uygularken
/// çağırır; yalnız KALICI KAYIT yazdırır, onay YAZMAZ. Aynı (proposal_id, content_hash)
/// tekrarı no-op'tur (idempotent). LLM metni veya proposal olayı onay kaynağı
/// DEĞİLDİR: onay yalnız <see cref="SubmitConfirmationAsync"/> açık eylemiyle alınır.</para>
///
/// <para><b>SubmitConfirmationAsync</b> — açık gönderim onayı: içerik hash'i geçerli
/// proposal sürümüne karşı, sahiplik run kaydına karşı ve süre sınırına karşı
/// doğrulanır; atomik koşullu güncellemeyle çift tıklama/ağ tekrarı/dağıtık yarışta
/// TEK onay kaydı üretilir (ikinci çağrı Duplicate, yeni kayıt yok). Kabulde
/// AgentActionResultV1 (accepted + applied_article_revision) AYNI transaction'da
/// outbox'a yazılır; sürüm/süre reddinde ret kararı gerekçesiyle (nedenle) ve
/// deterministik message_id ile TEK KEZ bildirilir; sahiplik reddinde ise mesaj
/// ÜRETİLMEZ (yetkisiz çağıran, agent kontrol akışına kayıt enjekte edemez).</para>
///
/// <para><b>ResumeRequestAsync</b> — onaylanmış ve hash'i beklenen sürümle eşleşen
/// proposal için AgentResumeRequestedV1 komutunu outbox'a yazar. Durum makinesi
/// proposed → confirmed → resume_sent koşullu güncellemeyle işletilir: aynı onay
/// için ikinci çağrı yeni mesaj ÜRETMEZ (Duplicate).</para>
///
/// Ziyaretçi düzenlemesi YENİ proposal sürümü olarak kaydedilir (düzenleme + onay tek
/// çağrıda: hash(edited_summary) ile gelen onay yeni sürümü onaylar — plan B9:
/// "Ziyaretçinin düzenlemesini yeni proposal sürümüyle ilişkilendir").
/// </summary>
public sealed class AgentCollaborationService(
    IUnitOfWork unitOfWork,
    IApplicationDbContext dbContext,
    IAgentCollaborationStore store,
    IOutboxWriter outboxWriter,
    IOptions<AgentMessagingSettings> messagingOptions,
    ILogger<AgentCollaborationService> logger)
{
    /// <summary>Projection hattının çağırdığı idempotent kalıcı kayıt; onay üretmez.</summary>
    public Task<ProposalUpsertResult> UpsertProposalAsync(
        Guid runId,
        Guid proposalId,
        string contentHash,
        string summary,
        string ownerKey,
        DateTimeOffset expiresAt,
        Guid articleId,
        long articleRevision,
        string baseContentHash,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(contentHash);
        ArgumentException.ThrowIfNullOrWhiteSpace(summary);
        ArgumentException.ThrowIfNullOrWhiteSpace(ownerKey);

        return store.UpsertProposalAsync(
            new AgentProposalUpsert(
                runId, proposalId, contentHash, summary, ownerKey, expiresAt,
                articleId, articleRevision, baseContentHash),
            cancellationToken);
    }

    /// <summary>Açık gönderim onayı; entegrasyon sözleşmesindeki giriş/çıkış biçimi korunur.
    /// <paramref name="editedSummary"/> verildiyse düzenleme YENİ SÜRÜM onayıdır:
    /// gönderilen hash SHA-256(edited_summary) olmak zorundadır.</summary>
    public async Task<CollaborateSubmitResult> SubmitConfirmationAsync(
        Guid runId,
        Guid proposalId,
        string submittedContentHash,
        string? editedSummary,
        string ownerKey,
        DateTimeOffset confirmedAt,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(submittedContentHash);
        ArgumentException.ThrowIfNullOrWhiteSpace(ownerKey);

        var hash = submittedContentHash.Trim();

        // Düzenleme + onay tek çağrı: hash, düzenlenen metnin özeti olmak zorunda
        // (istemcinin iddia ettiği sürümle gerçek içerik ayrışamaz).
        if (editedSummary is not null
            && !string.Equals(hash, AgentCollaborationContentHash.Compute(editedSummary), StringComparison.Ordinal))
        {
            return Rejected(CollaborateSubmitOutcome.RejectedVersion, confirmedAt,
                "gönderilen içerik hash'i düzenlenen özetle uyuşmuyor");
        }

        return (CollaborateSubmitResult)await unitOfWork.ExecuteResilientAsync(async ct =>
        {
            await using var transaction = await unitOfWork.BeginTransactionAsync(IsolationLevel.ReadCommitted, ct);

            // 1) Sahiplik backend'den doğrulanır (istemci owner alanı yetki kaynağı değildir).
            var run = await store.GetRunStateAsync(runId, ct);
            if (run is null)
            {
                return Rejected(CollaborateSubmitOutcome.RejectedVersion, confirmedAt, "run kaydı bulunamadı");
            }

            if (!string.Equals(run.OwnerKey, ownerKey, StringComparison.Ordinal))
            {
                // Yetkisiz çağıran: karar kaydı VE agent'a mesaj üretilmez.
                return Rejected(CollaborateSubmitOutcome.RejectedOwner, confirmedAt,
                    "bu çalışmanın iş birliği önerisi başka bir oturuma ait");
            }

            // 2) Proposal kaydı: projection'ın yazdığı güncel sürüm.
            var current = await store.GetCurrentProposalAsync(runId, proposalId, ct);
            if (current is null)
            {
                return Rejected(CollaborateSubmitOutcome.RejectedVersion, confirmedAt,
                    "bu çalışma için kayıtlı iş birliği önerisi yok");
            }

            // 3) Süre sınırı: backend politikası (plan B9 "süre sınırı").
            if (confirmedAt > current.ExpiresAt)
            {
                await WriteRejectionAsync(run, proposalId, hash,
                    "önerinin onay süresi doldu", confirmedAt, ct);
                await unitOfWork.SaveChangesAsync(ct);
                await transaction.CommitAsync(ct);
                return Rejected(CollaborateSubmitOutcome.RejectedVersion, confirmedAt,
                    "önerinin onay süresi doldu");
            }

            // 4) Sürüm bağlamı: onay belirli bir içerik sürümüne bağlıdır.
            var hashIsCurrent = string.Equals(hash, current.ContentHash, StringComparison.Ordinal);
            if (!hashIsCurrent && editedSummary is null)
            {
                // Değiştirilmiş/eskimiş proposal: öneri metni onaylandıktan sonra
                // değiştirilmiş olabilir; karar gerekçesiyle agent'a bildirilir.
                await WriteRejectionAsync(run, proposalId, hash,
                    "öneri içerik sürümü uyuşmuyor; güncel sürüm yeniden istenmeli", confirmedAt, ct);
                await unitOfWork.SaveChangesAsync(ct);
                await transaction.CommitAsync(ct);
                return Rejected(CollaborateSubmitOutcome.RejectedVersion, confirmedAt,
                    "öneri içerik sürümü uyuşmuyor; güncel sürüm yeniden istenmeli");
            }

            // 5) Düzenleme yeni sürüm olarak kaydedilir (hash current'tan farklıysa).
            var target = current;
            if (!hashIsCurrent)
            {
                var upsert = await store.UpsertProposalAsync(new AgentProposalUpsert(
                    runId, proposalId, hash, editedSummary!, current.OwnerKey,
                    current.ExpiresAt, current.ArticleId, current.ArticleRevision,
                    current.BaseContentHash), ct);
                target = await store.GetCurrentProposalAsync(runId, proposalId, ct)
                    ?? throw new InvalidOperationException("düzenleme sürümü kaydedilemedi");
                logger.LogInformation(
                    "[AgentCollab] düzenleme yeni sürüm olarak onaya bağlandı: proposal {ProposalId} v{Version}",
                    proposalId, upsert.Version);
            }

            if (!string.Equals(target.Status, AgentProposalStatus.Proposed, StringComparison.Ordinal))
            {
                // Onaylı/resume gönderilmiş öneri: aynı sürüm → idempotent Duplicate
                // (çift tıklama/ağ tekrarı); farklı sürüm → sürüm çatışması.
                if (string.Equals(hash, target.ConfirmedContentHash, StringComparison.Ordinal))
                {
                    return Duplicate(confirmedAt, target.Version);
                }

                return Rejected(CollaborateSubmitOutcome.RejectedVersion, confirmedAt,
                    "önerinin güncel sürümü zaten onaylanmış");
            }

            // 6) Atomik onay: koşullu UPDATE; yarışta TEK çağrı kazanır.
            var transition = await store.ConfirmAsync(target.RowId, hash, confirmedAt, ct);
            if (transition == ConfirmationTransition.VersionConflict)
            {
                return Rejected(CollaborateSubmitOutcome.RejectedVersion, confirmedAt,
                    "önerinin güncel sürümü zaten onaylanmış");
            }

            if (transition == ConfirmationTransition.Duplicate)
            {
                return Duplicate(confirmedAt, target.Version);
            }

            // 7) Kabul: gerçek backend sonucu AgentActionResultV1 ile agent'a —
            //    onay kaydıyla AYNI transaction'da (agent'ın bildirdiği başarı
            //    gerçek backend sonucuna bağlıdır).
            await WriteAcceptedResultAsync(run, target, confirmedAt, ct);
            await unitOfWork.SaveChangesAsync(ct);
            await transaction.CommitAsync(ct);

            logger.LogInformation(
                "[AgentCollab] onay kaydı: run {RunId} proposal {ProposalId} v{Version} hash {Hash}",
                runId, proposalId, target.Version, hash[..Math.Min(12, hash.Length)]);

            return new CollaborateSubmitResult(
                CollaborateSubmitOutcome.Accepted, confirmedAt, target.Version);
        }, cancellationToken);
    }

    /// <summary>Onaylanmış proposal için devam isteği; durum makinesi resume_sent'i
    /// koşullu yazar — aynı onay için ikinci resume ÜRETİLMEZ.</summary>
    public async Task<CollaborateResumeResult> ResumeRequestAsync(
        Guid runId,
        Guid proposalId,
        string expectedContentHash,
        string ownerKey,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(expectedContentHash);
        ArgumentException.ThrowIfNullOrWhiteSpace(ownerKey);

        var hash = expectedContentHash.Trim();
        var now = DateTimeOffset.UtcNow;

        return (CollaborateResumeResult)await unitOfWork.ExecuteResilientAsync(async ct =>
        {
            await using var transaction = await unitOfWork.BeginTransactionAsync(IsolationLevel.ReadCommitted, ct);

            var run = await store.GetRunStateAsync(runId, ct);
            if (run is null)
            {
                return new CollaborateResumeResult(
                    CollaborateResumeOutcome.RejectedVersion, now, "run kaydı bulunamadı");
            }

            if (!string.Equals(run.OwnerKey, ownerKey, StringComparison.Ordinal))
            {
                return new CollaborateResumeResult(
                    CollaborateResumeOutcome.RejectedOwner, now, "bu çalışma başka bir oturuma ait");
            }

            var current = await store.GetCurrentProposalAsync(runId, proposalId, ct);
            if (current is null)
            {
                return new CollaborateResumeResult(
                    CollaborateResumeOutcome.RejectedVersion, now, "kayıtlı iş birliği önerisi yok");
            }

            if (string.Equals(current.Status, AgentProposalStatus.Proposed, StringComparison.Ordinal)
                || (current.Status != AgentProposalStatus.Confirmed
                    && current.Status != AgentProposalStatus.ResumeSent))
            {
                // resume istemi yalnız ONAYLI kayıtla ilerler (onaysız işlem reddi).
                return new CollaborateResumeResult(
                    CollaborateResumeOutcome.RejectedVersion, now,
                    "öneri onaylanmadı; onaysız çalışma sürdürülemez");
            }

            if (!string.Equals(hash, current.ConfirmedContentHash ?? current.ContentHash, StringComparison.Ordinal))
            {
                return new CollaborateResumeResult(
                    CollaborateResumeOutcome.RejectedVersion, now,
                    "beklenen içerik sürümü onaylanan sürümle uyuşmuyor");
            }

            if (string.Equals(current.Status, AgentProposalStatus.ResumeSent, StringComparison.Ordinal))
            {
                // Aynı onay için ikinci resume ÜRETİLMEZ: yeni outbox kaydı yazılmaz.
                return new CollaborateResumeResult(CollaborateResumeOutcome.Duplicate, current.ConfirmedAt ?? now);
            }

            var transitioned = await store.MarkResumeSentAsync(current.RowId, ct);
            if (!transitioned)
            {
                // Yarış kaybedildi: kazanan zaten resume üretti (koşullu UPDATE).
                return new CollaborateResumeResult(CollaborateResumeOutcome.Duplicate, now);
            }

            var correlationId = Guid.NewGuid().ToString("D");
            var (envelopeJson, messageId) = AgentCollaborationEnvelopeComposer.ComposeResumeRequested(
                runId,
                run.ConversationId,
                correlationId,
                now,
                producer: messagingOptions.Value.ProducerName,
                checkpointReference: AgentCollaborationEnvelopeComposer.ComposeCheckpointReference(
                    runId, proposalId),
                userRef: current.OwnerKey,
                schemaVersion: run.WireVersion);

            var contractResult = new AgentContractValidator(messagingOptions.Value).Validate(envelopeJson);
            if (!contractResult.IsValid)
            {
                logger.LogWarning(
                    "[AgentCollab] resume zarfı sözleşme doğrulamasını geçemedi: {Field} {Detail}",
                    contractResult.Error!.Field, contractResult.Error.Message);
                return new CollaborateResumeResult(
                    CollaborateResumeOutcome.RejectedVersion, now,
                    "resume komutu sözleşme doğrulamasını geçemedi");
            }

            await outboxWriter.AddAsync(new OutboxMessage
            {
                MessageId = messageId,
                MessageType = AgentMessageTypes.ResumeRequested,
                Exchange = AgentMessageTypeRegistry.CommandsExchange,
                RoutingKey = AgentMessageTypeRegistry.RoutingKeyFor(run.WireVersion, AgentMessageTypes.ResumeRequested),
                CorrelationId = correlationId,
                RunId = runId,
                EnvelopeJson = envelopeJson,
                Status = AgentOutboxStatus.Pending,
            }, ct);
            await unitOfWork.SaveChangesAsync(ct);
            await transaction.CommitAsync(ct);

            logger.LogInformation(
                "[AgentCollab] resume komutu outbox'a yazıldı: run {RunId} proposal {ProposalId} (outbox {MessageId})",
                runId, proposalId, messageId);

            return new CollaborateResumeResult(CollaborateResumeOutcome.Sent, now);
        }, cancellationToken);
    }

    // ------------------------------------------------------------ yardımcılar

    private static CollaborateSubmitResult Rejected(CollaborateSubmitOutcome outcome, DateTimeOffset at, string reason) =>
        new(outcome, at, Version: 0, RejectionReason: reason);

    private static CollaborateSubmitResult Duplicate(DateTimeOffset at, long version) =>
        new(CollaborateSubmitOutcome.Duplicate, at, version);

    /// <summary>Kabul kararı: donuk B1 sözleşmesinin zorunlu applied_article_revision
    /// alanı proposal kaydındaki makale revizyonuyla yazılır (A1 ValidatedActionResult kuralı).</summary>
    private async Task WriteAcceptedResultAsync(
        CollaborationRunState run,
        AgentProposalSnapshot proposal,
        DateTimeOffset confirmedAt,
        CancellationToken ct)
    {
        var correlationId = Guid.NewGuid().ToString("D");
        var (envelopeJson, messageId) = AgentCollaborationEnvelopeComposer.ComposeActionResult(
            run.RunId,
            run.ConversationId,
            correlationId,
            confirmedAt,
            messagingOptions.Value.ProducerName,
            proposal.ProposalId,
            outcome: "accepted",
            reason: null,
            appliedArticleRevision: proposal.ArticleRevision,
            validatedAt: confirmedAt,
            schemaVersion: run.WireVersion);

        var contractResult = new AgentContractValidator(messagingOptions.Value).Validate(envelopeJson);
        if (!contractResult.IsValid)
        {
            // Onay kaydıyla mesaj üretimi aynı transaction'dadır: geçersiz zarf
            // onayı da geri alır (B3 deseni — hayalet kabul kaydı kalmaz).
            throw new InvalidOperationException(
                $"accepted ActionResult zarfı sözleşmeyi geçemedi: {contractResult.Error!.Field}");
        }

        await outboxWriter.AddAsync(new OutboxMessage
        {
            MessageId = messageId,
            MessageType = AgentMessageTypes.ActionResult,
            Exchange = AgentMessageTypeRegistry.CommandsExchange,
            RoutingKey = AgentMessageTypeRegistry.RoutingKeyFor(run.WireVersion, AgentMessageTypes.ActionResult),
            CorrelationId = correlationId,
            RunId = run.RunId,
            EnvelopeJson = envelopeJson,
            Status = AgentOutboxStatus.Pending,
        }, ct);
    }

    /// <summary>Ret kararı bildirimi: deterministik message_id + varlık kontrolüyle TEK
    /// kayıt (tekrarlı geçersiz gönderim agent'ı spam'lemez). Yetkisiz sahiplik
    /// reddinde BU YÖNTEM ÇAĞRILMAZ (mesaj üretilmez).</summary>
    private async Task WriteRejectionAsync(
        CollaborationRunState run,
        Guid proposalId,
        string submittedHash,
        string reason,
        DateTimeOffset at,
        CancellationToken ct)
    {
        var messageId = AgentCollaborationEnvelopeComposer.DeterministicRejectionMessageId(
            run.RunId, proposalId, submittedHash);
        var alreadyQueued = await dbContext.OutboxMessages
            .AsNoTracking()
            .AnyAsync(m => m.MessageId == messageId
                           && m.RunId == run.RunId
                           && m.Status != AgentOutboxStatus.DeadLettered, ct);
        if (alreadyQueued)
        {
            return;
        }

        var correlationId = Guid.NewGuid().ToString("D");
        var (envelopeJson, envelopeMessageId) = AgentCollaborationEnvelopeComposer.ComposeActionResult(
            run.RunId,
            run.ConversationId,
            correlationId,
            at,
            messagingOptions.Value.ProducerName,
            proposalId,
            outcome: "rejected",
            reason: reason,
            appliedArticleRevision: null,
            validatedAt: at,
            deterministicMessageId: messageId,
            schemaVersion: run.WireVersion);

        var contractResult = new AgentContractValidator(messagingOptions.Value).Validate(envelopeJson);
        if (!contractResult.IsValid)
        {
            logger.LogWarning(
                "[AgentCollab] ret zarfı sözleşmeyi geçemedi; ret bildirilmedi: {Field} {Detail}",
                contractResult.Error!.Field, contractResult.Error.Message);
            return;
        }

        await outboxWriter.AddAsync(new OutboxMessage
        {
            MessageId = envelopeMessageId,
            MessageType = AgentMessageTypes.ActionResult,
            Exchange = AgentMessageTypeRegistry.CommandsExchange,
            RoutingKey = AgentMessageTypeRegistry.RoutingKeyFor(run.WireVersion, AgentMessageTypes.ActionResult),
            CorrelationId = correlationId,
            RunId = run.RunId,
            EnvelopeJson = envelopeJson,
            Status = AgentOutboxStatus.Pending,
        }, ct);
    }
}
