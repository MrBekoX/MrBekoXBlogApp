using System.Data;
using System.Globalization;
using BlogApp.Core.Application.Common.Interfaces.Data;
using BlogApp.Core.Application.Common.Interfaces.Persistence;
using BlogApp.Core.Domain.Entities;
using BlogApp.Core.Domain.Enums;
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
/// <param name="SelectedMode">mode_selected olayında seçilen mod; diğerlerinde null.</param>
/// <param name="ProgressMessage">progressed olayındaki message alanı; bildirimde taşınır.</param>
/// <param name="SourceScope">Terminal sonuçta source_scope; diğerlerinde null.</param>
public sealed record AgentRunEventProjectionEvent(
    string ConsumerName,
    AgentEnvelope Envelope,
    string PayloadJson,
    long EventSequence,
    bool IsTerminal,
    AgentRunStatus? TerminalStatus = null,
    string? SelectedMode = null,
    string? ProgressMessage = null,
    string? SourceScope = null);

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
/// </summary>
public sealed class AgentRunEventProjectionHandler(
    IUnitOfWork unitOfWork,
    IApplicationDbContext dbContext,
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
            if (@event.SelectedMode is not null)
            {
                run.SelectedMode = @event.SelectedMode;
            }

            if (@event.IsTerminal)
            {
                run.Status = @event.TerminalStatus!.Value;
                run.ResultJson = @event.PayloadJson;
                run.TerminalAt = ParseUtc(@event.Envelope.OccurredAt);
                if (@event.SourceScope is not null)
                {
                    run.SourceScope = @event.SourceScope;
                }
            }

            await InsertInboxAsync(@event, messageId, runId, "applied", null, ct);
            await unitOfWork.SaveChangesAsync(ct);
            await transaction.CommitAsync(ct);

            logger.LogInformation(
                "[AgentProjection] olay uygulandı: run {RunId} seq {Seq} type {Type} status {Status}",
                runId, @event.EventSequence, @event.Envelope.MessageType, run.Status);

            var notification = new AgentRunNotification
            {
                RunId = runId.ToString("D"),
                MessageId = @event.Envelope.MessageId,
                MessageType = @event.Envelope.MessageType,
                Status = run.Status.ToString(),
                EventSequence = @event.EventSequence,
                Message = @event.ProgressMessage ?? string.Empty,
                OccurredAt = @event.Envelope.OccurredAt,
                ResultJson = @event.IsTerminal ? @event.PayloadJson : null,
            };
            return new AgentEventProjectionResult(
                AgentEventDecision.Apply, RunUnknown: false, InboxStatus: "applied", Notification: notification);
        }, cancellationToken);
    }

    private async Task InsertInboxAsync(
        AgentRunEventProjectionEvent @event,
        Guid messageId,
        Guid runId,
        string status,
        string? detail,
        CancellationToken ct)
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
