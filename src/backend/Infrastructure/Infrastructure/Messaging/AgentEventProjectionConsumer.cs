using System.Text.Json;
using System.Text.Json.Serialization;
using BlogApp.BuildingBlocks.Messaging;
using BlogApp.Core.Application.Common.Messaging;
using BlogApp.Core.Application.Common.Options;
using BlogApp.Core.Application.Features.AgentFeature.Collaboration;
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
    Microsoft.Extensions.Options.IOptions<AgentCollaborationSettings> collaborationOptions,
    ILogger<AgentEventProjectionConsumer> logger)
    : RabbitMqAgentConsumer(connections, settings, AgentMessagingTopology.BackendEventsQueue)
{
    public const string ConsumerName = AgentRunEventProjectionHandler.ConsumerName;

    private static readonly JsonSerializerOptions PayloadOptions = new()
    {
        NumberHandling = JsonNumberHandling.Strict
    };

    private readonly AgentContractValidator _validator = new();
    private readonly int _proposalValidityHours = collaborationOptions.Value.ProposalValidityHours;

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

        // Bildirim yalnız commit edilmiş Apply (veya reddedilen olayın güvenli Failed kapanışı)
        // kararında doludur; profil run'ındaki generation_delta bildirimi handler'da bastırılır.
        if ((result.Decision is AgentEventDecision.Apply or AgentEventDecision.Rejected) && result.Notification is not null)
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

    /// <summary>Payload'ı registry'nin (sürüm, tür) DTO türüne çözer ve projection girdisine eşler
    /// (K3: v1 ve v2 olayları kendi sürümünün DTO'suyla okunur; v1 backlog'u v1 olarak kalır).</summary>
    private AgentRunEventProjectionEvent BuildProjectionEvent(
        AgentEnvelope envelope, System.Text.Json.Nodes.JsonObject payloadNode)
    {
        var spec = AgentMessageTypeRegistry.TryGet(envelope.SchemaVersion, envelope.MessageType, out var messageSpec)
            ? messageSpec
            : throw new AgentEventRejectedException(
                "message_type", $"sözleşme v{envelope.SchemaVersion} içinde bilinmeyen mesaj türü: {envelope.MessageType}");

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

        // Terminal olay kesinleşmiş modu taşır: mode_selected olayı sırasız teslimde
        // stale düşse de run.SelectedMode terminal payload'dan dolar.
        return payload switch
        {
            AgentRunCompletedV1 completed => new AgentRunEventProjectionEvent(
                AgentRunEventProjectionHandler.ConsumerName, envelope, payloadJson, eventSequence,
                IsTerminal: true, TerminalStatus: AgentRunStatus.Completed,
                SelectedMode: completed.SelectedMode, SourceScope: completed.SourceScope),
            AgentRunPartiallyCompletedV1 partial => new AgentRunEventProjectionEvent(
                AgentRunEventProjectionHandler.ConsumerName, envelope, payloadJson, eventSequence,
                IsTerminal: true, TerminalStatus: AgentRunStatus.PartiallyCompleted,
                SelectedMode: partial.SelectedMode, SourceScope: partial.SourceScope),
            AgentRunFailedV1 failed => new AgentRunEventProjectionEvent(
                AgentRunEventProjectionHandler.ConsumerName, envelope, payloadJson, eventSequence,
                IsTerminal: true, TerminalStatus: AgentRunStatus.Failed,
                SelectedMode: failed.SelectedMode),
            AgentRunCompletedV2 completedV2 => new AgentRunEventProjectionEvent(
                AgentRunEventProjectionHandler.ConsumerName, envelope, payloadJson, eventSequence,
                IsTerminal: true, TerminalStatus: AgentRunStatus.Completed,
                SelectedMode: completedV2.SelectedMode, SourceScope: completedV2.SourceScope,
                RunIntent: completedV2.RunIntent, ProfileSnapshot: completedV2.ProfileSnapshot),
            AgentRunPartiallyCompletedV2 partialV2 => new AgentRunEventProjectionEvent(
                AgentRunEventProjectionHandler.ConsumerName, envelope, payloadJson, eventSequence,
                IsTerminal: true, TerminalStatus: AgentRunStatus.PartiallyCompleted,
                SelectedMode: partialV2.SelectedMode, SourceScope: partialV2.SourceScope,
                RunIntent: partialV2.RunIntent, ProfileSnapshot: partialV2.ProfileSnapshot),
            AgentRunFailedV2 failedV2 => new AgentRunEventProjectionEvent(
                AgentRunEventProjectionHandler.ConsumerName, envelope, payloadJson, eventSequence,
                IsTerminal: true, TerminalStatus: AgentRunStatus.Failed,
                SelectedMode: failedV2.SelectedMode,
                RunIntent: failedV2.RunIntent, ProfileSnapshot: failedV2.ProfileSnapshot),
            AgentRunModeSelectedV2 modeSelectedV2 => new AgentRunEventProjectionEvent(
                AgentRunEventProjectionHandler.ConsumerName, envelope, payloadJson, eventSequence,
                IsTerminal: false, SelectedMode: modeSelectedV2.SelectedMode,
                SourceScope: modeSelectedV2.SourceScope,
                RunIntent: modeSelectedV2.RunIntent, ProfileSnapshot: modeSelectedV2.ProfileSnapshot),
            AgentRunCancelledV1 cancelled => new AgentRunEventProjectionEvent(
                AgentRunEventProjectionHandler.ConsumerName, envelope, payloadJson, eventSequence,
                IsTerminal: true, TerminalStatus: AgentRunStatus.Cancelled),
            AgentRunModeSelectedV1 modeSelected => new AgentRunEventProjectionEvent(
                AgentRunEventProjectionHandler.ConsumerName, envelope, payloadJson, eventSequence,
                IsTerminal: false, SelectedMode: modeSelected.SelectedMode),
            AgentRunProgressedV1 progressed => new AgentRunEventProjectionEvent(
                AgentRunEventProjectionHandler.ConsumerName, envelope, payloadJson, eventSequence,
                IsTerminal: false, ProgressMessage: progressed.Message, ProgressKind: progressed.Kind),
            AgentRunAcceptedV1 => new AgentRunEventProjectionEvent(
                AgentRunEventProjectionHandler.ConsumerName, envelope, payloadJson, eventSequence, IsTerminal: false),
            AgentRunNeedsInputV1 => new AgentRunEventProjectionEvent(
                AgentRunEventProjectionHandler.ConsumerName, envelope, payloadJson, eventSequence, IsTerminal: false),
            AgentActionProposedV1 => new AgentRunEventProjectionEvent(
                AgentRunEventProjectionHandler.ConsumerName, envelope, payloadJson, eventSequence, IsTerminal: false,
                ProposalUpsert: BuildProposalUpsert(envelope, (AgentActionProposedV1)payload, _proposalValidityHours)),
            _ => throw new AgentEventRejectedException(
                "message_type", $"{envelope.MessageType} olay kuyruğunda işlenmez"),
        };
    }

    /// <summary>
    /// B9: AgentActionProposedV1'den kalıcı proposal upsert'i kurar. İçerik hash'i
    /// backend'in sakladığı düzenlenebilir içeriğin (summary) UTF-8 SHA-256 özetidir
    /// (D008 kuralı; B9 TEK TANIM — A9 üreticisi proposal_content_hash'i aynı
    /// özetin SHA-256'sı olarak üretir). Onay isteği bu sürüme karşı doğrulanır.
    /// Süre sınırı backend politikasıdır (AgentCollaborationSettings.ProposalValidityHours).
    /// Upsert yalnız KAYIT üretir — onay değildir (plan B9: onay açık backend eylemiyle alınır).
    /// Kimlik alanları kanonik UUID olmalıdır: proposal_id Python üreticisi
    /// (collab/proposal.py new_proposal_id) UUID taahhüdündedir; uymayan değer
    /// kalıcı sözleşme ihlalidir → DLX (FormatException yerine anlaşılır red).
    /// </summary>
    private static AgentProposalUpsert BuildProposalUpsert(
        AgentEnvelope envelope, AgentActionProposedV1 payload, int proposalValidityHours)
    {
        var occurredAt = DateTimeOffset.TryParse(
            envelope.OccurredAt, System.Globalization.CultureInfo.InvariantCulture,
            System.Globalization.DateTimeStyles.AssumeUniversal | System.Globalization.DateTimeStyles.AdjustToUniversal,
            out var parsed)
            ? parsed
            : DateTimeOffset.UtcNow;

        return new AgentProposalUpsert(
            RunId: ParseGuid(envelope.RunId!, "run_id"),
            ProposalId: ParseGuid(payload.ProposalId, "proposal_id"),
            ContentHash: AgentCollaborationContentHash.Compute(payload.Summary),
            Summary: payload.Summary,
            OwnerKey: string.Empty, // sahiplik handler'da kilitli run satırından tamamlanır
            ExpiresAt: occurredAt.AddHours(proposalValidityHours),
            ArticleId: ParseGuid(payload.ArticleId, "article_id"),
            ArticleRevision: payload.ArticleRevision,
            BaseContentHash: payload.BaseContentHash);
    }

    /// <summary>Kanonik UUID çözümü; uymayan değer kalıcı ihlal sayılır (DLX).</summary>
    private static Guid ParseGuid(string value, string field) =>
        Guid.TryParseExact(value, "D", out var parsed)
            ? parsed
            : throw new AgentEventRejectedException(
                field, $"kanonik UUID bekleniyordu: '{value}'");
}

/// <summary>Kalıcı sözleşme ihlali: mesaj DLX'e yönlendirilir (temel sınıf kuralı).</summary>
public sealed class AgentEventRejectedException(string field, string message)
    : Exception($"agent olay reddi ({field}): {message}");
