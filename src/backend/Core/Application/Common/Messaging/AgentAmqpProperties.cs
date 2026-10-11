namespace BlogApp.Core.Application.Common.Messaging;

/// <summary>
/// Zarf ile tutarlı ayarlanması gereken AMQP properties'leri (plan satır 233: message_id,
/// correlation_id, content_type). Yayın katmanı (B2/B3) bu değerleri broker properties'lerine kopyalar;
/// içerik türü daima JSON'dır ve pickle/serbest nesne deserialization kullanılmaz.
/// </summary>
public sealed record AgentAmqpProperties(string MessageId, string CorrelationId, string ContentType, string Type)
{
    public static AgentAmqpProperties FromEnvelope(AgentEnvelope envelope) => new(
        envelope.MessageId,
        envelope.CorrelationId,
        AgentMessageTypeRegistry.ContentType,
        envelope.MessageType);
}
