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
using BlogApp.Core.Application.Features.AgentFeature.Services;

namespace BlogApp.Core.Application.Features.AgentFeature.Commands.ResumeAgentRunCommand;

/// <summary>
/// B9 resume sözleşmesinin backend tarafındaki bekleyen devam durumu (B10 test
/// çiftiyle uyulan port). Tam depo uygulaması B9 iş birliği deposuyla gelir;
/// B10'un projection tabanlı uygulaması yalnız COMMIT EDİLMİŞ veriyi okur:
/// input sürümü en son uygulanan ``agent.run.needs_input`` olayının
/// event_sequence'idir (agent_event_inboxes), checkpoint/proposal bilgisi B9
/// kaydı gelene kadar YOKTUR — uydurulmaz (null; handler fail-closed davranır).
/// </summary>
public sealed record AgentResumePendingState
{
    /// <summary>En son uygulanan needs_input olayının event_sequence'i; bekleyen
    /// kullanıcı girdisi yoksa null.</summary>
    public long? InputVersion { get; init; }

    /// <summary>B9 iş birliği deposunun sakladığı checkpoint referansı; B9 kaydı
    /// yoksa null (backend bilmediği checkpoint kimliğini üretmez).</summary>
    public string? CheckpointReference { get; init; }

    /// <summary>Bekleyen ActionProposal kimliği (B9); yoksa null.</summary>
    public string? ProposalId { get; init; }

    /// <summary>Bekleyen proposal sürümü (B9); yoksa null.</summary>
    public long? ProposalVersion { get; init; }
}

/// <summary>B9 resume sözleşmesi portu (B10: projection okuma + test double; depo B9'da).</summary>
public interface IAgentResumeStateStore
{
    Task<AgentResumePendingState?> GetPendingAsync(Guid runId, CancellationToken cancellationToken = default);
}

/// <summary>
/// Projection + B9 iş birliği deposu tabanlı B10 uygulaması: yalnız COMMIT
/// EDİLMİŞ veriyi okur. Onaylanmış bir proposal kaydı (``agent_proposals``,
/// status=confirmed|resume_sent) varsa checkpoint referansı TEK TANIM'dan
/// (``AgentCollaborationEnvelopeComposer.ComposeCheckpointReference``) üretilir
/// — W6 F4 düzeltmesi: referansın HER ZAMAN null olması resume komutunun
/// üretimde asla yazılmaması demekti (mutlu yol yalnız test double'ıyla
/// geçiyordu). Checkpoint/proposal kaydı yoksa alanlar null kalır ve handler
/// fail-closed davranır (backend bilmediği checkpoint kimliğini üretmez).
/// </summary>
public sealed class ProjectionAgentResumeStateStore(IApplicationDbContext dbContext) : IAgentResumeStateStore
{
    public async Task<AgentResumePendingState?> GetPendingAsync(Guid runId, CancellationToken cancellationToken = default)
    {
        var inputVersion = await dbContext.AgentEventInboxes
            .AsNoTracking()
            .Where(i => i.ConsumerName == AgentRunEventProjectionHandler.ConsumerName
                        && i.RunId == runId
                        && i.MessageType == AgentMessageTypes.RunNeedsInput
                        && i.Status == "applied")
            .OrderByDescending(i => i.EventSequence)
            .Select(i => (long?)i.EventSequence)
            .FirstOrDefaultAsync(cancellationToken);

        var pendingProposal = await dbContext.AgentProposals
            .AsNoTracking()
            .Where(p => p.RunId == runId
                        && (p.Status == AgentProposalStatus.Confirmed
                            || p.Status == AgentProposalStatus.ResumeSent))
            .OrderByDescending(p => p.Version)
            .Select(p => new { p.ProposalId, p.Version })
            .FirstOrDefaultAsync(cancellationToken);

        if (inputVersion is null && pendingProposal is null)
        {
            return null;
        }

        return new AgentResumePendingState
        {
            InputVersion = inputVersion,
            CheckpointReference = pendingProposal is null
                ? null // onaylı proposal yok: backend checkpoint kimliği UYDURMAZ (fail-closed).
                : AgentCollaborationEnvelopeComposer.ComposeCheckpointReference(
                    runId, pendingProposal.ProposalId),
            ProposalId = pendingProposal?.ProposalId.ToString("D"),
            ProposalVersion = pendingProposal?.Version,
        };
    }
}

/// <summary>
/// Agent işine devam isteği (B10 endpoint'i; plan tablosu: "Beklenen input/proposal
/// sürümünü doğrulayan devam isteği" — B9 sözleşmesi). B3/B7 kabul desenini izler:
/// 1. Oturum + sahiplik backend'de doğrulanır (istemci owner alanı yetki kaynağı değildir).
/// 2. Terminal run'da resume reddedilir (already_terminal).
/// 3. Beklenen sürüm doğrulaması: istemcinin gördüğü input/proposal sürümü ile
///    commit edilmiş projection/B9-port durumu eşleşmezse Conflict — eski sürüme
///    göre devam komutu üretilmez (plan: "Beklenen input/proposal sürümünü doğrulayan").
/// 4. Checkpoint referansı YALNIZ doğrulanmış devam kaydından gelir: onaylı
///    proposal kaydı varsa TEK TANIM'dan üretilir (W6 F4); kayıt yoksa komut
///    ÜRETİLMEZ (fail-closed — backend bilmediği checkpoint kimliğini uydurmaz).
/// 5. Zarf commit öncesi sözleşme doğrulamasından geçer; resume komutu + run
///    değişmediğinden yalnız outbox kaydı TEK transaction'da yazılır.
/// 6. 202 anlamlı kabul: komut outbox'tadır; graph devamı Python kontrol
///    consumer'ının B9 sürücüsündedir (``CollaborationResumeDriver``).
/// </summary>
public sealed class ResumeAgentRunCommandHandler(
    IUnitOfWork unitOfWork,
    IApplicationDbContext dbContext,
    ICurrentUserService currentUser,
    IOutboxWriter outboxWriter,
    IAgentResumeStateStore resumeStateStore,
    IOptions<AgentMessagingSettings> messagingOptions,
    ILogger<ResumeAgentRunCommandHandler> logger) : IRequestHandler<ResumeAgentRunCommandRequest, Result<AgentRunResumeDto>>
{
    public async Task<Result<AgentRunResumeDto>> Handle(ResumeAgentRunCommandRequest request, CancellationToken cancellationToken)
    {
        // 1) Oturum doğrulama: kullanıcı JWT kimliği veya sunucu üretiği misafir oturumu.
        var userId = currentUser.UserId;
        var guestSessionId = request.GuestSessionId?.Trim();
        if (userId is null && string.IsNullOrWhiteSpace(guestSessionId))
        {
            return Result<AgentRunResumeDto>.Failure(Error.Unauthorized("Agent işi için oturum gereklidir."));
        }

        var ownerKey = userId is not null ? $"u:{userId.Value:D}" : $"g:{guestSessionId}";
        var requestedAt = DateTimeOffset.UtcNow;

        // 2) Sahiplik + terminal durumu.
        var run = await dbContext.AgentRuns
            .AsNoTracking()
            .FirstOrDefaultAsync(r => r.Id == request.RunId, cancellationToken);
        if (run is null)
        {
            return Result<AgentRunResumeDto>.Failure(Error.NotFound("Agent işi bulunamadı."));
        }

        if (!string.Equals(run.OwnerKey, ownerKey, StringComparison.Ordinal))
        {
            return Result<AgentRunResumeDto>.Failure(Error.Forbidden("Bu agent işi başka bir oturuma ait."));
        }

        if (run.Status.IsTerminal())
        {
            return Result<AgentRunResumeDto>.Failure(Error.Domain(
                "Tamamlanmış veya sonlanmış bir iş devam ettirilemez."));
        }

        if (request.ExpectedInputVersion.HasValue == request.ExpectedProposalVersion.HasValue
            || request.ExpectedInputVersion is < 0 || request.ExpectedProposalVersion is <= 0)
        {
            return Result<AgentRunResumeDto>.Failure(Error.Validation(new Dictionary<string, string[]>
            {
                ["ExpectedVersion"] = ["Exactly one expected version is required (input >= 0, proposal >= 1)."],
            }));
        }

        // 3) Beklenen sürüm doğrulaması — commit edilmiş projection/B9-port durumuyla.
        var pending = await resumeStateStore.GetPendingAsync(request.RunId, cancellationToken);
        if (pending is null)
        {
            return Result<AgentRunResumeDto>.Failure(Error.Conflict(
                "Bu iş için bekleyen bir devam kaydı yok (needs_input veya proposal beklenmiyor)."));
        }

        if (request.ExpectedInputVersion is { } expectedInput)
        {
            if (pending.InputVersion is null || pending.InputVersion.Value != expectedInput)
            {
                return Result<AgentRunResumeDto>.Failure(Error.Conflict(
                    "Beklenen girdi sürümü güncel değil; sayfayı yenileyip en son soruyu kullanın."));
            }
        }
        else if (request.ExpectedProposalVersion is { } expectedProposal)
        {
            if (pending.ProposalVersion is null || pending.ProposalVersion.Value != expectedProposal)
            {
                return Result<AgentRunResumeDto>.Failure(Error.Conflict(
                    "Beklenen proposal sürümü güncel değil; iş birliği kaydı yenilenmiş olabilir."));
            }
        }

        // 4) Checkpoint kaydı olmadan zarf ÜRETİLMEZ (fail-closed; B9 deposu beklemede).
        if (string.IsNullOrWhiteSpace(pending.CheckpointReference))
        {
            logger.LogInformation(
                "[AgentResume] run {RunId} için bekleyen girdi sürümü {Version} doğrulandı ama checkpoint kaydı yok (B9 deposu beklemede); komut üretilmedi",
                request.RunId, pending.InputVersion ?? pending.ProposalVersion);
            return Result<AgentRunResumeDto>.Failure(Error.Conflict(
                "Devam kaydı hazır değil: checkpoint referansı henüz backend'e kaydedilmedi (B9 iş birliği deposu beklemede)."));
        }

        // 5) Tek transaction: açık resume komutu idempotency + zarf doğrulaması + outbox.
        try
        {
            return await unitOfWork.ExecuteResilientAsync(async ct =>
            {
                await using var transaction = await unitOfWork.BeginTransactionAsync(System.Data.IsolationLevel.ReadCommitted, ct);

                // Serialize with projection, collaboration and deadline recovery.
                // The preflight state may have changed while this request waited.
                var lockedRun = await dbContext.AgentRuns
                    .FromSql($"SELECT * FROM agent_runs WHERE \"Id\" = {request.RunId} FOR UPDATE")
                    .AsNoTracking().FirstOrDefaultAsync(ct);
                if (lockedRun is null || lockedRun.OwnerKey != ownerKey || lockedRun.Status.IsTerminal()
                    || lockedRun.DeadlineAt <= DateTime.UtcNow)
                    return Result<AgentRunResumeDto>.Failure(Error.Conflict("Çalışma artık devam ettirilebilir durumda değil."));
                var lockedPending = await resumeStateStore.GetPendingAsync(request.RunId, ct);
                if (lockedPending is null || string.IsNullOrWhiteSpace(lockedPending.CheckpointReference)
                    || (request.ExpectedInputVersion.HasValue && lockedPending.InputVersion != request.ExpectedInputVersion)
                    || (request.ExpectedProposalVersion.HasValue && lockedPending.ProposalVersion != request.ExpectedProposalVersion))
                    return Result<AgentRunResumeDto>.Failure(Error.Conflict("Beklenen devam sürümü artık güncel değil."));

                var openResumeExists = await dbContext.OutboxMessages
                    .AsNoTracking()
                    .AnyAsync(m => m.RunId == request.RunId
                                   && m.MessageType == AgentMessageTypes.ResumeRequested
                                   && m.Status != AgentOutboxStatus.DeadLettered, ct);
                if (openResumeExists)
                {
                    return Result<AgentRunResumeDto>.Success(new AgentRunResumeDto(
                        request.RunId, "replay", requestedAt));
                }

                var userRef = userId is not null ? $"u:{userId.Value:D}" : $"g:{guestSessionId}";
                // correlation_id sözleşmede kanonik UUID'dir; HTTP TraceIdentifier gibi
                // UUID olmayan iz değerleri sözleşmeye uygun GUID ile değiştirilir
                // (B10 bulgusu: üretimde cancel'ı da etkileyen gizli hata).
                var callerCorrelation = currentUser.CorrelationId;
                var correlationId = Guid.TryParseExact(callerCorrelation, "D", out var callerCorrelationId)
                    ? callerCorrelationId.ToString("D")
                    : Guid.NewGuid().ToString("D");
                // K4: resume komutu run'ın wire sürümünü korur.
                var wireVersion = AgentRunWireContext.Parse(run.ContextSnapshotJson).WireVersion;
                var (envelopeJson, messageId) = AgentResumeEnvelopeComposer.ComposeResumeRequested(
                    request.RunId,
                    run.ConversationId,
                    correlationId,
                    requestedAt,
                    producer: messagingOptions.Value.ProducerName,
                    checkpointReference: lockedPending.CheckpointReference,
                    userRef: userRef,
                    schemaVersion: wireVersion);

                var contractResult = new AgentContractValidator(messagingOptions.Value).Validate(envelopeJson);
                if (!contractResult.IsValid)
                {
                    logger.LogWarning(
                        "[AgentResume] resume zarfı sözleşme doğrulamasını geçemedi: {Field} {Detail}",
                        contractResult.Error!.Field, contractResult.Error.Message);
                    return Result<AgentRunResumeDto>.Failure(Error.Domain(
                        "Devam komutu sözleşme doğrulamasını geçemedi; istek kaydedilmedi."));
                }

                var outboxMessage = new OutboxMessage
                {
                    MessageId = messageId,
                    MessageType = AgentMessageTypes.ResumeRequested,
                    Exchange = AgentMessageTypeRegistry.CommandsExchange,
                    RoutingKey = AgentMessageTypeRegistry.RoutingKeyFor(wireVersion, AgentMessageTypes.ResumeRequested),
                    CorrelationId = correlationId,
                    RunId = request.RunId,
                    EnvelopeJson = envelopeJson,
                    Status = AgentOutboxStatus.Pending,
                };
                await outboxWriter.AddAsync(outboxMessage, ct);
                await unitOfWork.SaveChangesAsync(ct);
                await transaction.CommitAsync(ct);

                logger.LogInformation(
                    "[AgentResume] run {RunId} için resume komutu outbox'a yazıldı (outbox {MessageId})",
                    request.RunId, messageId);

                return Result<AgentRunResumeDto>.Success(new AgentRunResumeDto(
                    request.RunId, "accepted", requestedAt));
            }, cancellationToken);
        }
        catch (DbUpdateException exception)
        {
            logger.LogWarning(exception, "[AgentResume] resume komutu yazımı başarısız (run {RunId})", request.RunId);
            return Result<AgentRunResumeDto>.Failure(Error.Conflict(
                "Devam isteği kaydedilemedi; isteği tekrarlayın."));
        }
    }
}
