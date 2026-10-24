using System.Data;
using System.Globalization;
using BlogApp.Core.Application.Common.Interfaces.Data;
using BlogApp.Core.Application.Common.Interfaces.Persistence;
using BlogApp.Core.Application.Features.AgentFeature.Collaboration;
using BlogApp.Core.Application.Features.AgentFeature.Services;
using BlogApp.Core.Domain.Entities;
using BlogApp.Core.Domain.Enums;
using BlogApp.Core.Application.Features.AgentFeature.Services;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging;

namespace BlogApp.Core.Application.Common.Messaging;

/// <summary>Doğrulanmış tek agent olayının projection girdisi; consumer üretir.</summary>
/// <param name="ConsumerName">Tüketici kimliği (inbox PK bileşeni).</param>
/// <param name="Envelope">B1 doğrulayıcıdan geçmiş zarf.</param>
/// <param name="PayloadJson">Payload'ın JSON'u; terminal olayda kalıcı snapshot olarak yazılır.</param>
/// <param name="EventSequence">Payload event_sequence (run başına monoton).</param>
/// <param name="IsTerminal">completed/partially_completed/failed/cancelled türleri için true.</param>
/// <param name="TerminalStatus">Terminal olayda hedef AgentRunStatus; diğerlerinde null.</param>
/// <param name="SelectedMode">mode_selected olayında seçilen mod; terminal olaylarda kesinleşmiş mod (yalnız run modu boşsa uygulanır); diğerlerinde null.</param>
/// <param name="ProgressMessage">progressed olayındaki message alanı; bildirimde taşınır.</param>
/// <param name="SourceScope">Terminal sonuçta source_scope; diğerlerinde null.</param>
/// <param name="ProposalUpsert">AgentActionProposedV1 olayının kalıcı proposal upsert'i
/// (B9, ADDITIVE): consumer doldurur; Apply kararında aynı transaction'da store'a yazılır.
/// Upsert yalnız KAYIT üretir; onay üretmez (onay açık backend eylemidir).</param>
/// <param name="RunIntent">v2 mode_selected/terminal olaylarının etkin niyeti (run_intent); v1'de null.</param>
/// <param name="ProfileSnapshot">v2 olayın taşıdığı profil sürümü; kabulde pinlenen sürümle karşılaştırılır.</param>
/// <param name="ProgressKind">progressed olayının kind alanı (generation_delta bastırması için).</param>
public sealed record AgentRunEventProjectionEvent(
    string ConsumerName,
    AgentEnvelope Envelope,
    string PayloadJson,
    long EventSequence,
    bool IsTerminal,
    AgentRunStatus? TerminalStatus = null,
    string? SelectedMode = null,
    string? ProgressMessage = null,
    string? SourceScope = null,
    AgentProposalUpsert? ProposalUpsert = null,
    string? RunIntent = null,
    AgentProfileSnapshotRef? ProfileSnapshot = null,
    string? ProgressKind = null);

/// <summary>Bir olayın projection sonucu.</summary>
/// <param name="Decision">Saf kural kararları: Apply/Duplicate/Stale.</param>
/// <param name="RunUnknown">run_id backend'de yok: sınırlı quarantine politikası uygulandı.</param>
/// <param name="InboxStatus">Yazılan inbox durumu (applied | stale | quarantined).</param>
/// <param name="Notification">Yalnız commit edilmiş Apply kararında doludur.</param>
public sealed record AgentEventProjectionResult(
    AgentEventDecision Decision,
    bool RunUnknown,
    string InboxStatus,
    AgentRunNotification? Notification)
{
    public static AgentEventProjectionResult Duplicate() =>
        new(AgentEventDecision.Duplicate, RunUnknown: false, InboxStatus: "duplicate", Notification: null);
}

/// <summary>
/// B5 projection işleyicisi (plan B5 backend listesi): olay doğrulaması çağıran
/// consumer'dadır (B1 <see cref="AgentContractValidator"/>); bu sınıf doğrulanmış
/// olayı alır ve inbox kaydı + AgentRun projection değişikliğini TEK
/// transaction'da yapar. Commit'ten sonra ACK verilir (consumer sorumluluğu);
/// tekrarlı olay aynı projection'a yeniden UYGULANMAZ (inbox PK benzersizliği);
/// geç gelen eski olay terminal durumu geriye götürmez
/// (<see cref="AgentRunEventProjectionRules"/>); bilinmeyen run_id kalıcı
/// ``quarantined`` inbox kaydıyla ACK'lanır (sınırlı politika: sonsuz retry yok).
/// W6 F6: terminal bildiriminin ResultJson'ı GET ile AYNI
/// <see cref="IAgentResultPresentationGuard"/> denetiminden geçer — yayın
/// erişimini kaybetmiş makaleye dayanan sonuç push'ta maskelenir (istemci
/// tazelemeyi guard'lı GET'ten yapar). K6 profil politikası da aynı guard'dadır.
///
/// Who am I (K4/K6) EK KURALLARI:
/// - Olay ↔ run bağlamı (<see cref="AgentRunEventWireRules"/>): schema_version run'ın wire sürümüne
///   eşit olmalı; v2 who_am_i run'ında run_intent profile olmalı; profile_snapshot kabulde
///   pinlenen sürüme eşit olmalı. KARAR (belgelenmiş): ihlal eden olay sözleşme ihlali gibi
///   REDDEDİLİR — projection'a UYGULANMAZ, payload'ı saklanmaz, inbox'a ``rejected`` (gerekçeli,
///   payload'sız) yazılır ve run terminal değilse güvenli biçimde Failed'a kapatılır
///   (backend üretimli validation_error sonucu; içerik yok). Böylece run kotayı süresiz tutmaz
///   (periyodik backend reaper'a ek savunma), tekrar teslim inbox PK'siyle yeniden işlenmez ve ACK verilir
///   (DLQ döngüsü kurulmaz; bilinmeyen run'daki ``quarantined`` politikasının eşdeğeri).
/// - v2 mode_selected'ın source_scope'u run'a yazılır (etkin kapsam; terminal sonuç üzerine yazar).
///   run_intent mode_selected inbox payload'ında ve terminal ResultJson'da kalıcıdır (yeni kolon yok).
/// - Profil run'ında (konu who_am_i veya etkin kapsam profile) generation_delta olayları SignalR'a
///   GÖNDERİLMEZ ve inbox'a gövdesiz (message/detail'siz) yazılır; replay de gövde döndürmez.
/// </summary>
public sealed class AgentRunEventProjectionHandler(
    IUnitOfWork unitOfWork,
    IApplicationDbContext dbContext,
    IAgentCollaborationStore collaborationStore,
    IAgentResultPresentationGuard presentationGuard,
    ILogger<AgentRunEventProjectionHandler> logger)
{
    public const string ConsumerName = "backend-agent-events";

    /// <summary>Doğrulanmış tek agent olayını projection'a uygular; dönüş commit sonrasıdır.</summary>
    public async Task<AgentEventProjectionResult> ApplyAsync(
        AgentRunEventProjectionEvent @event,
        CancellationToken cancellationToken = default)
    {
        var messageId = Guid.Parse(@event.Envelope.MessageId);
        var runId = Guid.Parse(@event.Envelope.RunId!);

        // Hızlı yol: bu mesaj daha önce işlendi mi? (yarışta transaction içi ikinci
        // kontrol + PK benzersizliği güvence verir.)
        var seenBefore = await dbContext.AgentEventInboxes
            .AsNoTracking()
            .AnyAsync(i => i.ConsumerName == @event.ConsumerName && i.MessageId == messageId, cancellationToken);
        if (seenBefore)
        {
            return AgentEventProjectionResult.Duplicate();
        }

        return await unitOfWork.ExecuteResilientAsync(async ct =>
        {
            await using var transaction = await unitOfWork.BeginTransactionAsync(IsolationLevel.ReadCommitted, ct);

            // Run satırını kilitler: eşzamanlı olay teslimlerini sıralar, terminal-
            // öncelik ve sequence okuması tutarlı olur ([PG-ISOLATION] FOR UPDATE).
            var run = await dbContext.AgentRuns
                .FromSql($"SELECT * FROM agent_runs WHERE \"Id\" = {runId} FOR UPDATE")
                .FirstOrDefaultAsync(ct);

            if (run is null)
            {
                await InsertInboxAsync(@event, messageId, runId, "quarantined",
                    "run kaydı bulunamadı; olay karantinaya alındı", ct);
                await unitOfWork.SaveChangesAsync(ct);
                await transaction.CommitAsync(ct);
                logger.LogWarning(
                    "[AgentProjection] bilinmeyen run karantinaya alındı: run {RunId} message {MessageId} type {Type}",
                    runId, messageId, @event.Envelope.MessageType);
                return new AgentEventProjectionResult(
                    AgentEventDecision.Stale, RunUnknown: true, InboxStatus: "quarantined", Notification: null);
            }

            // Transaction içi ikinci tekrar kontrolü (lock beklemede ikiz teslim commit olabilir).
            var duplicateInsideTx = await dbContext.AgentEventInboxes
                .AsNoTracking()
                .AnyAsync(i => i.ConsumerName == @event.ConsumerName && i.MessageId == messageId, ct);
            if (duplicateInsideTx)
            {
                await transaction.RollbackAsync(ct);
                return AgentEventProjectionResult.Duplicate();
            }

            var decision = AgentRunEventProjectionRules.Decide(
                duplicateDelivery: false,
                runIsTerminal: run.Status.IsTerminal(),
                lastAppliedSequence: run.LastEventSequence,
                incomingSequence: @event.EventSequence,
                incomingIsTerminal: @event.IsTerminal);

            var wireContext = AgentRunWireContext.Parse(run.ContextSnapshotJson);
            if (decision == AgentEventDecision.Apply)
            {
                var violation = AgentRunEventWireRules.Verify(
                    wireContext,
                    @event.Envelope.SchemaVersion,
                    @event.Envelope.MessageType,
                    @event.RunIntent,
                    @event.ProfileSnapshot);
                if (violation is not null)
                {
                    return await RejectAsync(@event, run, messageId, runId, violation, transaction, ct);
                }
            }

            if (decision == AgentEventDecision.Stale)
            {
                await InsertInboxAsync(@event, messageId, runId, "stale",
                    $"sıra gerilemesi veya terminal sonrası eski olay: son uygulanan {run.LastEventSequence}, gelen {@event.EventSequence}", ct);
                await unitOfWork.SaveChangesAsync(ct);
                await transaction.CommitAsync(ct);
                logger.LogInformation(
                    "[AgentProjection] eski olay yoksayıldı: run {RunId} seq {Seq} (son {Last}) type {Type}",
                    runId, @event.EventSequence, run.LastEventSequence, @event.Envelope.MessageType);
                return new AgentEventProjectionResult(
                    AgentEventDecision.Stale, RunUnknown: false, InboxStatus: "stale", Notification: null);
            }

            // Apply: projection değişikliği + inbox kaydı TEK transaction'da.
            run.LastEventSequence = @event.EventSequence;
            // mode_selected modu belirler; terminal olay yalnız mode_selected hiç
            // uygulanmamışsa (sırasız teslimde stale düştüyse) boşluğu doldurur.
            if (@event.SelectedMode is not null && (!@event.IsTerminal || run.SelectedMode is null))
            {
                run.SelectedMode = @event.SelectedMode;
            }

            // v2 mode_selected etkin kapsamı (K6) ve terminal kapsam aynı kolona yazılır.
            if (@event.SourceScope is not null)
            {
                run.SourceScope = @event.SourceScope;
            }

            // Profil run'ında doğrulanmamış cevap parçası yayınlanmaz/saklanmaz (K6, A25).
            var suppressDelta = IsSuppressedDelta(@event, wireContext, run.SourceScope);

            // B9: proposal olayı uygulandıysa kalıcı proposal kaydı AYNI transaction'da
            // upsert edilir (idempotent; aynı sürüm tekrarı no-op). Kayıt onay DEĞİLDİR:
            // onay yalnız açık backend eylemiyle alınır (AgentCollaborationService).
            // Sahiplik istemciden gelmez: kilitli run satırının OwnerKey'i yazılır.
            if (@event.ProposalUpsert is { } proposalUpsert)
            {
                var ownedUpsert = proposalUpsert with { OwnerKey = run.OwnerKey };
                var upsert = await collaborationStore.UpsertProposalAsync(ownedUpsert, ct);
                logger.LogInformation(
                    "[AgentProjection] proposal kaydı: run {RunId} proposal {ProposalId} v{Version} ({Outcome})",
                    runId, ownedUpsert.ProposalId, upsert.Version, upsert.Outcome);
            }

            if (@event.IsTerminal)
            {
                run.Status = @event.TerminalStatus!.Value;
                run.ResultJson = @event.PayloadJson;
                run.TerminalAt = ParseUtc(@event.Envelope.OccurredAt);
            }

            await InsertInboxAsync(@event, messageId, runId, "applied", null, ct,
                payloadJson: suppressDelta ? SuppressedDeltaPayload(@event.EventSequence) : @event.PayloadJson,
                progressMessage: suppressDelta ? null : @event.ProgressMessage);
            await unitOfWork.SaveChangesAsync(ct);
            await transaction.CommitAsync(ct);

            logger.LogInformation(
                "[AgentProjection] olay uygulandı: run {RunId} seq {Seq} type {Type} status {Status}",
                runId, @event.EventSequence, @event.Envelope.MessageType, run.Status);

            // W6 F6: push yolu GET ile AYNI sunum denetiminden geçer (B8 kuralı
            // "sunmadan önce yayın erişim denetimi"). Yayından kalkmış/silinmiş
            // makaleye dayanan terminal sonuç SignalR push payload'ında TAŞINMAZ;
            // istemci durum/status bildirimini alır, içeriği guard'lı GET'ten
            // ("içerik kullanılamıyor" kararıyla) tazeler. Denetim yalnız okur;
            // projection kaydı değişmez.
            var pushResultJson = @event.IsTerminal ? @event.PayloadJson : null;
            if (pushResultJson is not null)
            {
                var presentation = await presentationGuard.CheckAsync(
                    new AgentRunResultContext(runId, run.ArticleId, pushResultJson, run.ContextSnapshotJson), ct);
                if (!presentation.IsPresentable)
                {
                    pushResultJson = null;
                    logger.LogInformation(
                        "[AgentProjection] terminal sonuç push'ta maskelendi ({Reason}): run {RunId}",
                        presentation.UnavailableReason, runId);
                }
            }

            if (suppressDelta)
            {
                logger.LogDebug(
                    "[AgentProjection] profil run'ında generation_delta push edilmedi: run {RunId} seq {Seq}",
                    runId, @event.EventSequence);
                return new AgentEventProjectionResult(
                    AgentEventDecision.Apply, RunUnknown: false, InboxStatus: "applied", Notification: null);
            }

            var notification = new AgentRunNotification
            {
                RunId = runId.ToString("D"),
                MessageId = @event.Envelope.MessageId,
                MessageType = @event.Envelope.MessageType,
                Status = run.Status.ToString(),
                EventSequence = @event.EventSequence,
                Message = @event.ProgressMessage ?? string.Empty,
                OccurredAt = @event.Envelope.OccurredAt,
                ResultJson = pushResultJson,
            };
            return new AgentEventProjectionResult(
                AgentEventDecision.Apply, RunUnknown: false, InboxStatus: "applied", Notification: notification);
        }, cancellationToken);
    }

    /// <summary>Profil run'ında (konu who_am_i veya etkin kapsam profile) generation_delta olayı.</summary>
    public static bool IsSuppressedDelta(AgentRunEventProjectionEvent @event, AgentRunWireContext wireContext, string? runSourceScope) =>
        string.Equals(@event.Envelope.MessageType, AgentMessageTypes.RunProgressed, StringComparison.Ordinal)
        && string.Equals(@event.ProgressKind, "generation_delta", StringComparison.Ordinal)
        && (wireContext.IsWhoAmI || string.Equals(runSourceScope, "profile", StringComparison.Ordinal));

    /// <summary>Gövdesiz delta kaydı: replay kind'ı türetebilir, metin/detay saklanmaz.</summary>
    private static string SuppressedDeltaPayload(long eventSequence) =>
        string.Create(System.Globalization.CultureInfo.InvariantCulture,
            $"{{\"event_sequence\":{eventSequence},\"kind\":\"generation_delta\",\"message\":\"-\"}}");

    /// <summary>Sürüm/profil tutarlılığı ihlali (K4/K6): olay uygulanmaz; inbox ``rejected`` +
    /// run terminal değilse güvenli Failed kapanışı (içeriksiz backend sonucu).</summary>
    private async Task<AgentEventProjectionResult> RejectAsync(
        AgentRunEventProjectionEvent @event,
        AgentRun run,
        Guid messageId,
        Guid runId,
        string violation,
        ITransactionScope transaction,
        CancellationToken ct)
    {
        var detail = violation.Length > AgentRunEventWireRules.MaxReasonLength
            ? violation[..AgentRunEventWireRules.MaxReasonLength]
            : violation;
        await InsertInboxAsync(@event, messageId, runId, "rejected", detail, ct);

        AgentRunNotification? notification = null;
        if (!run.Status.IsTerminal())
        {
            run.Status = AgentRunStatus.Failed;
            run.ResultJson = RejectionResultJson(@event.Envelope.MessageType);
            run.TerminalAt = DateTime.UtcNow;
            run.LastEventSequence = Math.Max(run.LastEventSequence, @event.EventSequence);
            notification = new AgentRunNotification
            {
                RunId = runId.ToString("D"),
                MessageId = @event.Envelope.MessageId,
                MessageType = AgentMessageTypes.RunFailed,
                Status = run.Status.ToString(),
                EventSequence = run.LastEventSequence,
                OccurredAt = AgentCommandEnvelopeComposer.FormatUtc(DateTimeOffset.UtcNow),
            };
        }

        await unitOfWork.SaveChangesAsync(ct);
        await transaction.CommitAsync(ct);
        logger.LogWarning(
            "[AgentProjection] olay reddedildi (run sözleşmesi ihlali): run {RunId} message {MessageId} type {Type}: {Violation}",
            runId, messageId, @event.Envelope.MessageType, detail);
        return new AgentEventProjectionResult(
            AgentEventDecision.Rejected, RunUnknown: false, InboxStatus: "rejected", Notification: notification);
    }

    /// <summary>Reddedilen olayın yerine yazılan backend sonucu: içerik/kaynak taşımaz.</summary>
    public static string RejectionResultJson(string rejectedMessageType) =>
        System.Text.Json.JsonSerializer.Serialize(new Dictionary<string, string>
        {
            ["error_code"] = "validation_error",
            ["error_message"] = "Agent olayı run sözleşmesini ihlal etti; sonuç sunulmadı.",
            ["rejected_message_type"] = rejectedMessageType,
        });

    private async Task InsertInboxAsync(
        AgentRunEventProjectionEvent @event,
        Guid messageId,
        Guid runId,
        string status,
        string? detail,
        CancellationToken ct,
        string? payloadJson = null,
        string? progressMessage = null)
    {
        await dbContext.AgentEventInboxes.AddAsync(new AgentEventInbox
        {
            ConsumerName = @event.ConsumerName,
            MessageId = messageId,
            MessageType = @event.Envelope.MessageType,
            RunId = runId,
            EventSequence = @event.EventSequence,
            Status = status,
            Detail = detail,
            // Agent live-steps replay türetme kaynağı (ADDITIVE): yalnız UYGULANAN
            // kayıt replay'in parçasıdır; stale/quarantined satırlar payload'sız kalır.
            PayloadJson = payloadJson,
            ProgressMessage = progressMessage,
            CreatedAt = DateTime.UtcNow,
        }, ct);
    }

    private static DateTime? ParseUtc(string occurredAt) =>
        DateTimeOffset.TryParse(
            occurredAt,
            CultureInfo.InvariantCulture,
            DateTimeStyles.AssumeUniversal | DateTimeStyles.AdjustToUniversal,
            out var parsed)
            ? parsed.UtcDateTime
            : null;
}
