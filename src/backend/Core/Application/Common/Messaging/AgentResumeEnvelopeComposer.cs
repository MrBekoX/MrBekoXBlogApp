using System.Text.Json;
using BlogApp.Core.Application.Common.Messaging;

namespace BlogApp.Core.Application.Common.Messaging;

/// <summary>
/// Resume komut zarfı üreticisi (B10; B9 sözleşmesinin B1 zarf karşılığı).
/// B7'deki <see cref="AgentControlEnvelopeComposer"/> ile aynı additive desen:
/// B1'in donuk dosyalarına ekleme YAPILMAZ; komut zarfı ayrı bir üreticide kurulur,
/// payload B1 DTO'su (<see cref="AgentResumeRequestedV1"/>) ile taşınır ve üretilen
/// zarf commit öncesi <see cref="AgentContractValidator"/> ile doğrulanır (B3 deseni:
/// geçersiz zarf komut üretmez). Zamanlar UTC ISO 8601; opsiyonel null alanlar taşınmaz.
/// </summary>
public static class AgentResumeEnvelopeComposer
{
    /// <summary>agent.resume.requested zarfı üretir; dönüş (zarf JSON'u, message_id).
    /// message_id outbox kaydına yazılır ve tekrar yayınlarda korunur (plan satır 301).
    /// checkpoint_reference backend'in doğruladığı devam kaydından gelir (B9 sözleşmesi);
    /// user_ref oturum sahipliğini doğrulayan backend kimliğidir, yetki KAYNAĞI değildir.</summary>
    public static (string EnvelopeJson, string MessageId) ComposeResumeRequested(
        Guid runId,
        Guid conversationId,
        string correlationId,
        DateTimeOffset occurredAt,
        string producer,
        string checkpointReference,
        string userRef)
    {
        var messageId = Guid.NewGuid().ToString("D");

        var envelope = new AgentEnvelope
        {
            MessageId = messageId,
            MessageType = AgentMessageTypes.ResumeRequested,
            SchemaVersion = AgentMessageTypeRegistry.SchemaVersion,
            RunId = runId.ToString("D"),
            ConversationId = conversationId.ToString("D"),
            CorrelationId = correlationId,
            OccurredAt = AgentCommandEnvelopeComposer.FormatUtc(occurredAt),
            Producer = producer,
            DeliveryAttempt = 0,
            Payload = JsonSerializer.SerializeToElement(
                new AgentResumeRequestedV1
                {
                    CheckpointReference = checkpointReference,
                    UserRef = userRef,
                },
                AgentCommandEnvelopeComposer.SerializerOptions),
        };

        return (JsonSerializer.Serialize(envelope, AgentCommandEnvelopeComposer.SerializerOptions), messageId);
    }
}
