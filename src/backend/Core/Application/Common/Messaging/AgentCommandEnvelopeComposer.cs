using System.Globalization;
using System.Text.Json;
using System.Text.Json.Serialization;
using BlogApp.Core.Application.Common.Messaging;

namespace BlogApp.Core.Application.Common.Messaging;

/// <summary>
/// Backend komut zarfı üreticisi (B3): AgentExecutionRequested zarfını B1 sözleşme DTO'larından
/// kurar ve JSON'a çevirir. Zamanlar UTC ISO 8601, kimlikler kanonik UUID (AgentContractFormats);
/// opsiyonel null alanlar JSON'da taşınmaz (sözleşme kuralı). Üretilen zarf kabul transaction'ı
/// commit edilmeden AgentContractValidator ile doğrulanır; geçersiz zarf komut üretmez.
/// </summary>
public static class AgentCommandEnvelopeComposer
{
    public static readonly JsonSerializerOptions SerializerOptions = new()
    {
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
    };

    /// <summary>ExecutionRequested zarfı üretir; dönüş (zarf JSON'u, message_id). message_id outbox
    /// kaydına yazılır ve tekrar yayınlarda korunur (plan satır 301).</summary>
    public static (string EnvelopeJson, string MessageId) ComposeExecutionRequested(
        Guid runId,
        Guid conversationId,
        string correlationId,
        DateTimeOffset occurredAt,
        DateTimeOffset deadlineAt,
        string producer,
        string userRef,
        string question,
        string language,
        string modePreference,
        string budgetProfile,
        string? contextSnapshotReference,
        string? selectedText)
    {
        var messageId = Guid.NewGuid().ToString("D");

        var envelope = new AgentEnvelope
        {
            MessageId = messageId,
            MessageType = AgentMessageTypes.ExecutionRequested,
            SchemaVersion = AgentMessageTypeRegistry.SchemaVersion,
            RunId = runId.ToString("D"),
            ConversationId = conversationId.ToString("D"),
            CorrelationId = correlationId,
            OccurredAt = FormatUtc(occurredAt),
            DeadlineAt = FormatUtc(deadlineAt),
            Producer = producer,
            DeliveryAttempt = 0,
            Payload = JsonSerializer.SerializeToElement(
                new AgentExecutionRequestedV1
                {
                    UserRef = userRef,
                    Question = question,
                    Language = language,
                    ModePreference = modePreference,
                    BudgetProfile = budgetProfile,
                    ContextSnapshotReference = contextSnapshotReference,
                    SelectedText = selectedText,
                },
                SerializerOptions),
        };

        return (JsonSerializer.Serialize(envelope, SerializerOptions), messageId);
    }

    /// <summary>Tekrar yayında yalnızca transport tekrar sayacı güncellenir; message_id dahil
    /// diğer alanlar korunur (plan satır 301: kayıp confirm aynı message_id ile yeniden yayınlanır).</summary>
    public static string WithDeliveryAttempt(string envelopeJson, int deliveryAttempt)
    {
        var envelope = JsonSerializer.Deserialize<AgentEnvelope>(envelopeJson, SerializerOptions)
            ?? throw new InvalidOperationException("Outbox zarfı çözümlenemedi.");
        return JsonSerializer.Serialize(
            envelope with { DeliveryAttempt = deliveryAttempt },
            SerializerOptions);
    }

    public static string FormatUtc(DateTimeOffset value) =>
        value.UtcDateTime.ToString("yyyy-MM-dd'T'HH:mm:ss.fff'Z'", CultureInfo.InvariantCulture);
}
