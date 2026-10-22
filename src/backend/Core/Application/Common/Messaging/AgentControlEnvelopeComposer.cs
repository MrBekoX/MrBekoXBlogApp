using System.Text.Json;
using BlogApp.Core.Application.Common.Messaging;

namespace BlogApp.Core.Application.Common.Messaging;

/// <summary>
/// Kontrol komut zarfı üreticisi (B7): iptal isteğinin B1 sözleşme zarfını kurar.
/// B1'in <see cref="AgentCommandEnvelopeComposer"/>'ına ekleme YAPILMAZ (B1 dosyaları
/// donmuştur); B5/B8'deki gibi aynı klasörde AYRI additive üretici olarak durur
/// (öncül: AgentContentEventComposer). Zamanlar UTC ISO 8601, opsiyonel null
/// alanlar JSON'da taşınmaz; üretilen zarf commit öncesi AgentContractValidator
/// ile doğrulanır (B3 deseni: geçersiz zarf komut üretmez).
/// </summary>
public static class AgentControlEnvelopeComposer
{
    /// <summary>CancellationRequested zarfı üretir; dönüş (zarf JSON'u, message_id).
    /// message_id outbox kaydına yazılır ve tekrar yayınlarda korunur (plan satır 301).</summary>
    /// <param name="schemaVersion">Run'ın kabulde kararlaşan wire sürümü (K4); kontrol komutları
    /// run'ın sürümünü korur (v1 run → v1, v2 run → v2).</param>
    public static (string EnvelopeJson, string MessageId) ComposeCancellationRequested(
        Guid runId,
        Guid conversationId,
        string correlationId,
        DateTimeOffset occurredAt,
        string producer,
        string? reason,
        int schemaVersion = AgentMessageTypeRegistry.V1)
    {
        AgentMessageTypeRegistry.Get(schemaVersion, AgentMessageTypes.CancellationRequested);
        var messageId = Guid.NewGuid().ToString("D");

        var envelope = new AgentEnvelope
        {
            MessageId = messageId,
            MessageType = AgentMessageTypes.CancellationRequested,
            SchemaVersion = schemaVersion,
            RunId = runId.ToString("D"),
            ConversationId = conversationId.ToString("D"),
            CorrelationId = correlationId,
            OccurredAt = AgentCommandEnvelopeComposer.FormatUtc(occurredAt),
            Producer = producer,
            DeliveryAttempt = 0,
            Payload = JsonSerializer.SerializeToElement(
                new AgentCancellationRequestedV1
                {
                    Reason = reason,
                },
                AgentCommandEnvelopeComposer.SerializerOptions),
        };

        return (JsonSerializer.Serialize(envelope, AgentCommandEnvelopeComposer.SerializerOptions), messageId);
    }
}
