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
    /// kaydına yazılır ve tekrar yayınlarda korunur (plan satır 301). Makale bağlamı
    /// article_id/article_revision/article_content_hash ÜÇLÜSÜ halinde taşınır (B1 sözleşme
    /// all-or-none kuralı; W5 bulgusu 4i): biri varsa üçü birden yazılır, hiçbiri yoksa alan
    /// yazılmaz (makalesiz genel sorular). <paramref name="schemaVersion"/> run'ın kabulde kararlaşan
    /// wire sürümüdür (K4): v1 donuk şekli, v2 konu + pinlenmiş profil + tamamlanmış geçmişi taşır.</summary>
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
        string? selectedText,
        string? articleId = null,
        long? articleRevision = null,
        string? articleContentHash = null,
        int schemaVersion = AgentMessageTypeRegistry.V1,
        string? conversationTopic = null,
        AgentProfileSnapshotRef? profileSnapshot = null,
        IReadOnlyList<AgentConversationTurn>? conversationHistory = null)
    {
        var hasAny = articleId is not null || articleRevision is not null || articleContentHash is not null;
        var hasAll = articleId is not null && articleRevision is not null && articleContentHash is not null;
        if (hasAny && !hasAll)
        {
            throw new ArgumentException(
                "Makale referansı article_id/article_revision/article_content_hash üçlüsü halinde taşınır (B1 all-or-none); eksik üçlü komut üretmez.");
        }

        // Sürüm kaydı yoksa üretici hatasıdır (registry dışı (sürüm, tür) komut üretmez).
        AgentMessageTypeRegistry.Get(schemaVersion, AgentMessageTypes.ExecutionRequested);

        object payload;
        if (schemaVersion == AgentMessageTypeRegistry.V1)
        {
            // v1 donuk sözleşme: konu/profil/geçmiş alanı YOKTUR; v1 run'ları eski şekliyle üretilir.
            if (conversationTopic is not null || profileSnapshot is not null || conversationHistory is { Count: > 0 })
            {
                throw new ArgumentException(
                    "v1 execute komutu conversation_topic/profile_snapshot/conversation_history taşımaz (v1 donuk sözleşme).");
            }

            payload = new AgentExecutionRequestedV1
            {
                UserRef = userRef,
                Question = question,
                Language = language,
                ModePreference = modePreference,
                BudgetProfile = budgetProfile,
                ContextSnapshotReference = contextSnapshotReference,
                SelectedText = selectedText,
                ArticleId = articleId,
                ArticleRevision = articleRevision,
                ArticleContentHash = articleContentHash,
            };
        }
        else
        {
            payload = new AgentExecutionRequestedV2
            {
                UserRef = userRef,
                Question = question,
                Language = language,
                ModePreference = modePreference,
                BudgetProfile = budgetProfile,
                ContextSnapshotReference = contextSnapshotReference,
                SelectedText = selectedText,
                ArticleId = articleId,
                ArticleRevision = articleRevision,
                ArticleContentHash = articleContentHash,
                ConversationHistory = conversationHistory is { Count: > 0 } ? [.. conversationHistory] : null,
                ConversationTopic = conversationTopic
                    ?? throw new ArgumentException("v2 execute komutu conversation_topic gerektirir.", nameof(conversationTopic)),
                ProfileSnapshot = profileSnapshot,
            };
        }

        var messageId = Guid.NewGuid().ToString("D");

        var envelope = new AgentEnvelope
        {
            MessageId = messageId,
            MessageType = AgentMessageTypes.ExecutionRequested,
            SchemaVersion = schemaVersion,
            RunId = runId.ToString("D"),
            ConversationId = conversationId.ToString("D"),
            CorrelationId = correlationId,
            OccurredAt = FormatUtc(occurredAt),
            DeadlineAt = FormatUtc(deadlineAt),
            Producer = producer,
            DeliveryAttempt = 0,
            Payload = JsonSerializer.SerializeToElement(payload, payload.GetType(), SerializerOptions),
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
