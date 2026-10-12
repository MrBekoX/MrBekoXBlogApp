using System.Data;
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

namespace BlogApp.Core.Application.Features.AgentFeature.Commands.CancelAgentRunCommand;

/// <summary>
/// Agent işi iptal talebi (B7; plan satır 427: "Backend sahipliği doğrulayıp
/// cancel intent ve outbox kaydını atomik yazsın"). B3 kabul deseninin iptal
/// karşılığı:
/// 1. Oturum doğrulama — kimlik JWT'den veya sunucu tarafı misafir oturumundan;
///    istemcinin owner alanı yetki kaynağı değildir.
/// 2. Sahiplik — run OwnerKey'i istek sahibiyle eşleşmezse Forbidden.
/// 3. Zaten terminal ise istek kaydedilmez (already_terminal) — geç terminal
///    geri götürülmez.
/// 4. Idempotency — aynı iş için açık (DeadLettered olmayan) cancel komutu
///    varsa yeni kayıt yazılmaz (replay yanıtı).
/// 5. Cancel komut zarfı commit ÖNCESİ AgentContractValidator'dan geçirilir;
///    komut, AgentRun üstündeki backend iptal kaydı olarak TEK transaction'da
///    outbox'a yazılır (kalıcı niyet kaydı: RunId + agent.cancel.requested +
///    Pending; terminal kararı agent cancel_intents + terminal-öncelik
///    kuralıyla atomikleşir — B6/B7 ortak store sözleşmesi).
/// 6. Başarılı yanıt "requested": cancel intent kaydı TERMINAL DEĞİLDİR;
///    arayüz "iptal isteniyor" gösterir, terminali agent.run.cancelled olayı
///    projection'ı getirir (B5).
/// </summary>
public sealed class CancelAgentRunCommandHandler(
    IUnitOfWork unitOfWork,
    IApplicationDbContext dbContext,
    ICurrentUserService currentUser,
    IOutboxWriter outboxWriter,
    IOptions<AgentMessagingSettings> messagingOptions,
    ILogger<CancelAgentRunCommandHandler> logger) : IRequestHandler<CancelAgentRunCommandRequest, Result<AgentRunCancelDto>>
{
    public async Task<Result<AgentRunCancelDto>> Handle(CancelAgentRunCommandRequest request, CancellationToken cancellationToken)
    {
        // 1) Oturum doğrulama: kullanıcı JWT kimliği veya sunucu üretiği misafir oturumu.
        var userId = currentUser.UserId;
        var guestSessionId = request.GuestSessionId?.Trim();
        if (userId is null && string.IsNullOrWhiteSpace(guestSessionId))
        {
            return Result<AgentRunCancelDto>.Failure(Error.Unauthorized("Agent işi için oturum gereklidir."));
        }

        var ownerKey = userId is not null ? $"u:{userId.Value:D}" : $"g:{guestSessionId}";
        var requestedAt = DateTimeOffset.UtcNow;

        // 2) Sahiplik ve terminal durumu: run backend kaydı üzerinden doğrulanır.
        var run = await dbContext.AgentRuns
            .AsNoTracking()
            .FirstOrDefaultAsync(r => r.Id == request.RunId, cancellationToken);
        if (run is null)
        {
            return Result<AgentRunCancelDto>.Failure(Error.NotFound("Agent işi bulunamadı."));
        }

        if (!string.Equals(run.OwnerKey, ownerKey, StringComparison.Ordinal))
        {
            return Result<AgentRunCancelDto>.Failure(Error.Forbidden("Bu agent işi başka bir oturuma ait."));
        }

        if (run.Status.IsTerminal())
        {
            logger.LogInformation(
                "[AgentCancel] run {RunId} zaten terminal ({Status}); iptal isteği kaydedilmez",
                run.Id, run.Status);
            return Result<AgentRunCancelDto>.Success(new AgentRunCancelDto(
                run.Id, "already_terminal", requestedAt));
        }

        var reason = request.Reason?.Trim();
        if (reason is { Length: > 2000 })
        {
            return Result<AgentRunCancelDto>.Failure(Error.Domain(
                "İptal gerekçesi en fazla 2000 karakter olabilir."));
        }

        // 3) Tek transaction: idempotency + zarf doğrulaması + outbox kaydı.
        try
        {
            return await unitOfWork.ExecuteResilientAsync(async ct =>
            {
                await using var transaction = await unitOfWork.BeginTransactionAsync(IsolationLevel.ReadCommitted, ct);

                var openCancelExists = await dbContext.OutboxMessages
                    .AsNoTracking()
                    .AnyAsync(m => m.RunId == request.RunId
                                   && m.MessageType == AgentMessageTypes.CancellationRequested
                                   && m.Status != AgentOutboxStatus.DeadLettered, ct);
                if (openCancelExists)
                {
                    logger.LogInformation(
                        "[AgentCancel] run {RunId} için açık cancel komutu var; replay yanıtı", request.RunId);
                    return Result<AgentRunCancelDto>.Success(new AgentRunCancelDto(
                        request.RunId, "replay", requestedAt));
                }

                // correlation_id sözleşmede kanonik UUID'dir; HTTP TraceIdentifier gibi
                // UUID olmayan iz değerleri sözleşmeye uygun GUID ile değiştirilir
                // (B10'un resume hattında bulunan gizli hatanın cancel karşılığı).
                var callerCorrelation = currentUser.CorrelationId;
                var correlationId = Guid.TryParseExact(callerCorrelation, "D", out var callerCorrelationId)
                    ? callerCorrelationId.ToString("D")
                    : Guid.NewGuid().ToString("D");
                var (envelopeJson, messageId) = AgentControlEnvelopeComposer.ComposeCancellationRequested(
                    request.RunId,
                    run.ConversationId,
                    correlationId,
                    requestedAt,
                    producer: messagingOptions.Value.ProducerName,
                    reason: string.IsNullOrEmpty(reason) ? null : reason);

                var contractResult = new AgentContractValidator(messagingOptions.Value).Validate(envelopeJson);
                if (!contractResult.IsValid)
                {
                    logger.LogWarning(
                        "[AgentCancel] cancel zarfı sözleşme doğrulamasını geçemedi: {Field} {Detail}",
                        contractResult.Error!.Field, contractResult.Error.Message);
                    return Result<AgentRunCancelDto>.Failure(Error.Domain(
                        "İptal komutu sözleşme doğrulamasını geçemedi; istek kaydedilmedi."));
                }

                var outboxMessage = new OutboxMessage
                {
                    MessageId = messageId,
                    MessageType = AgentMessageTypes.CancellationRequested,
                    Exchange = AgentMessageTypeRegistry.CommandsExchange,
                    RoutingKey = "agent.cancel.requested.v1",
                    CorrelationId = correlationId,
                    RunId = request.RunId,
                    EnvelopeJson = envelopeJson,
                    Status = AgentOutboxStatus.Pending,
                };
                await outboxWriter.AddAsync(outboxMessage, ct);
                await unitOfWork.SaveChangesAsync(ct);
                await transaction.CommitAsync(ct);

                logger.LogInformation(
                    "[AgentCancel] run {RunId} için cancel komutu outbox'a yazıldı (outbox {MessageId})",
                    request.RunId, messageId);

                return Result<AgentRunCancelDto>.Success(new AgentRunCancelDto(
                    request.RunId, "requested", requestedAt));
            }, cancellationToken);
        }
        catch (DbUpdateException exception)
        {
            logger.LogWarning(exception, "[AgentCancel] cancel komutu yazımı başarısız (run {RunId})", request.RunId);
            return Result<AgentRunCancelDto>.Failure(Error.Conflict(
                "İptal isteği kaydedilemedi; isteği tekrarlayın."));
        }
    }
}
