using System.Text.Json;
using System.Text.Json.Serialization;
using BlogApp.BuildingBlocks.Messaging;
using BlogApp.Core.Application.Common.Messaging;
using BlogApp.Core.Domain.Enums;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging;

namespace BlogApp.Infrastructure.Messaging;

/// <summary>
/// B5 olay tüketici servisi (plan B5 backend listesi): ``backend.agent.events.q``
/// teslimlerini B1 doğrulayıcıdan geçirir, projection işleyicisine verir ve
/// commit sonrası ACK alır (temel sınıf HandleAsync normal döndükten sonra ACK
/// eder; projection commit'i ondan önce tamamlanmıştır).
///
/// Sorumluluk bölümü:
/// - Kalıcı sözleşme ihlali (şema/yön/üretici) → istisna → temel sınıf
///   ``BasicNackAsync(requeue: false)`` ile DLX'e düşürür (sürekli requeue yok).
/// - Geçici DB hatası → aynı DLX yolu; transport retry ayrımı B7 kapsamıdır
///   (bilinçli B5 sınırı, raporda kayıtlı).
/// - Bilinmeyen run_id kalıcı business koşuldur: projection işleyicisi
///   ``quarantined`` inbox kaydını yazar; consumer mesajı ACK'lar (sınırlı
///   politika: sonsuz retry/DLQ döngüsü kurulmaz).
/// - UI bildirimi projection commit'inden SONRA best-effort yapılır; bildirim
///   hatası projection'ı geri almaz ve ACK'ı engellemez (plan: "SignalR gönderildi
///   bilgisini kullanıcı okudu garantisi sayma").
/// </summary>
public sealed class AgentEventProjectionConsumer(
    IRabbitMqConnectionManager connections,
    RabbitMqSettings settings,
    IServiceScopeFactory scopeFactory,
    ILogger<AgentEventProjectionConsumer> logger)
    : RabbitMqAgentConsumer(connections, settings, AgentMessagingTopology.BackendEventsQueue)
{
    public const string ConsumerName = AgentRunEventProjectionHandler.ConsumerName;

    private static readonly JsonSerializerOptions PayloadOptions = new()
    {
        NumberHandling = JsonNumberHandling.Strict
    };

    private readonly AgentContractValidator _validator = new();

    protected override async Task HandleAsync(
        string exchange,
        string routingKey,
        byte[] body,
        RabbitMQ.Client.Events.BasicDeliverEventArgs delivery,
        CancellationToken cancellationToken)
    {
        var validation = _validator.Validate(body);
        if (!validation.IsValid)
        {
            // Kalıcı ihlal: DLX'e (temel sınıf nack requeue:false). Tekrar işlenmez.
            logger.LogWarning(
                "[AgentEvents] sözleşme reddi: kategori {Category} alan {Field} mesaj {MessageId}",
                validation.Error!.Category, validation.Error.Field, validation.Envelope?.MessageId);
            throw new AgentEventRejectedException(validation.Error!.Field, validation.Error.Message);
        }

        var envelope = validation.Envelope!;
        logger.LogInformation(
            "[AgentEvents] teslim işleniyor: type {Type} message {MessageId} run {RunId} rk {RoutingKey}",
            envelope.MessageType, envelope.MessageId, envelope.RunId, routingKey);
        var payloadEvent = BuildProjectionEvent(envelope, validation.PayloadNode!);

        await using var scope = scopeFactory.CreateAsyncScope();
        var handler = scope.ServiceProvider.GetRequiredService<AgentRunEventProjectionHandler>();

        var result = await handler.ApplyAsync(payloadEvent, cancellationToken);

        if (result.Decision == AgentEventDecision.Apply && result.Notification is not null)
        {
            // Commit edilmiş projection üzerinden UI bildirimi (best-effort).
            var notifier = scope.ServiceProvider.GetRequiredService<IAgentRunNotifier>();
            try
            {
                await notifier.NotifyAsync(result.Notification, cancellationToken);
            }
            catch (Exception notificationError)
            {
                logger.LogWarning(notificationError,
                    "[AgentEvents] UI bildirimi başarısız (projection commit'li): run {RunId} mesaj {MessageId}",
                    result.Notification.RunId, result.Notification.MessageId);
            }
        }
    }

    /// <summary>Payload'ı registry DTO türüne çözer ve projection girdisine eşler.</summary>
    private static AgentRunEventProjectionEvent BuildProjectionEvent(
        AgentEnvelope envelope, System.Text.Json.Nodes.JsonObject payloadNode)
    {
        var spec = AgentMessageTypeRegistry.TryGet(envelope.MessageType, out var messageSpec)
            ? messageSpec
            : throw new AgentEventRejectedException("message_type", $"bilinmeyen mesaj türü: {envelope.MessageType}");

        AgentPayloadBase? payload;
        try
        {
            payload = (AgentPayloadBase?)payloadNode.Deserialize(spec.PayloadDtoType, PayloadOptions);
        }
        catch (JsonException exception)
        {
            throw new AgentEventRejectedException("payload", $"payload DTO çözümlemesi başarısız: {exception.Message}");
        }

        if (payload is null)
        {
            throw new AgentEventRejectedException("payload", "payload boş çözümlendi");
        }

        if (payload.ExtensionData is { Count: > 0 })
        {
            throw new AgentEventRejectedException(
                "payload", $"bilinmeyen payload alanı: {payload.ExtensionData.Keys.First()}");
        }

        var eventSequence = payload is AgentRunEventPayloadBase runEvent
            ? runEvent.EventSequence
            : 0; // registry'deki tüm run olayları AgentRunEventPayloadBase'ten türer

        var payloadJson = payloadNode.ToJsonString(PayloadOptions);

        return payload switch
        {
            AgentRunCompletedV1 completed => new AgentRunEventProjectionEvent(
                AgentRunEventProjectionHandler.ConsumerName, envelope, payloadJson, eventSequence,
                IsTerminal: true, TerminalStatus: AgentRunStatus.Completed,
                SourceScope: completed.SourceScope),
            AgentRunPartiallyCompletedV1 partial => new AgentRunEventProjectionEvent(
                AgentRunEventProjectionHandler.ConsumerName, envelope, payloadJson, eventSequence,
                IsTerminal: true, TerminalStatus: AgentRunStatus.PartiallyCompleted,
                SourceScope: partial.SourceScope),
            AgentRunFailedV1 failed => new AgentRunEventProjectionEvent(
                AgentRunEventProjectionHandler.ConsumerName, envelope, payloadJson, eventSequence,
                IsTerminal: true, TerminalStatus: AgentRunStatus.Failed),
            AgentRunCancelledV1 cancelled => new AgentRunEventProjectionEvent(
                AgentRunEventProjectionHandler.ConsumerName, envelope, payloadJson, eventSequence,
                IsTerminal: true, TerminalStatus: AgentRunStatus.Cancelled),
            AgentRunModeSelectedV1 modeSelected => new AgentRunEventProjectionEvent(
                AgentRunEventProjectionHandler.ConsumerName, envelope, payloadJson, eventSequence,
                IsTerminal: false, SelectedMode: modeSelected.SelectedMode),
            AgentRunProgressedV1 progressed => new AgentRunEventProjectionEvent(
                AgentRunEventProjectionHandler.ConsumerName, envelope, payloadJson, eventSequence,
                IsTerminal: false, ProgressMessage: progressed.Message),
            AgentRunAcceptedV1 => new AgentRunEventProjectionEvent(
                AgentRunEventProjectionHandler.ConsumerName, envelope, payloadJson, eventSequence, IsTerminal: false),
            AgentRunNeedsInputV1 => new AgentRunEventProjectionEvent(
                AgentRunEventProjectionHandler.ConsumerName, envelope, payloadJson, eventSequence, IsTerminal: false),
            AgentActionProposedV1 => new AgentRunEventProjectionEvent(
                AgentRunEventProjectionHandler.ConsumerName, envelope, payloadJson, eventSequence, IsTerminal: false),
            _ => throw new AgentEventRejectedException(
                "message_type", $"{envelope.MessageType} olay kuyruğunda işlenmez"),
        };
    }
}

/// <summary>Kalıcı sözleşme ihlali: mesaj DLX'e yönlendirilir (temel sınıf kuralı).</summary>
public sealed class AgentEventRejectedException(string field, string message)
    : Exception($"agent olay reddi ({field}): {message}");
