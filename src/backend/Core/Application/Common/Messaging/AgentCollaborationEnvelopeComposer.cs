using System.Security.Cryptography;
using System.Text.Json;
using BlogApp.Core.Application.Common.Messaging;

namespace BlogApp.Core.Application.Common.Messaging;

/// <summary>
/// İş birliği kontrol komut zarfları (B9): ResumeRequested ve ActionResult zarflarını
/// donuk B1 sözleşme DTO'larından kurar. B1'in <see cref="AgentCommandEnvelopeComposer"/>'ına
/// ve B7'nin <see cref="AgentControlEnvelopeComposer"/>'ına ekleme YAPILMAZ (donuk
/// dosyalar); B5/B7/B8 örneğindeki gibi AYRI additive üretici olarak durur. Zamanlar
/// UTC ISO 8601, opsiyonel null alanlar JSON'da taşınmaz; üretilen zarf commit
/// öncesi AgentContractValidator ile doğrulanır (B3 deseni: geçersiz zarf komut üretmez).
/// </summary>
public static class AgentCollaborationEnvelopeComposer
{
    /// <summary>Ret kararlarının tekilleştirilmiş message_id ad alanı (rastgele değil:
    /// aynı (proposal, sürüm, karar) tekrarı aynı kaydı paylaşır — tekrarlı ret
    /// gönderimi tek outbox kaydıyla karşılanır).</summary>
    private static readonly Guid RejectionNamespace = new("6f1f0b9a-3b9c-4d8e-9b9a-5b9c011ab001");

    /// <summary>
    /// Checkpoint referansı TEK TANIM (W6 F4): resume komutunun taşıdığı referans
    /// B10 resume store'u (``ProjectionAgentResumeStateStore``) ile B9 iş birliği
    /// servisi (``ResumeRequestAsync``) tarafından AYNI biçimle üretilir —
    /// uyuşmayan iki üretici aynı çalışmaya iki farklı referans götürürdü.
    /// Referans gözlemlenebilirlik taşıyıcısıdır: agent checkpoint zinciri
    /// ``job-{run_id}`` kararlı kimliğiyle çözülür (A8 sözleşmesi).
    /// </summary>
    public static string ComposeCheckpointReference(Guid runId, Guid proposalId) =>
        $"agent-collab/{runId:D}/proposal/{proposalId:D}";

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

    public static (string EnvelopeJson, string MessageId) ComposeActionResult(
        Guid runId,
        Guid conversationId,
        string correlationId,
        DateTimeOffset occurredAt,
        string producer,
        Guid proposalId,
        string outcome,
        string? reason,
        long? appliedArticleRevision,
        DateTimeOffset validatedAt,
        string? deterministicMessageId = null)
    {
        var messageId = deterministicMessageId ?? Guid.NewGuid().ToString("D");

        var envelope = new AgentEnvelope
        {
            MessageId = messageId,
            MessageType = AgentMessageTypes.ActionResult,
            SchemaVersion = AgentMessageTypeRegistry.SchemaVersion,
            RunId = runId.ToString("D"),
            ConversationId = conversationId.ToString("D"),
            CorrelationId = correlationId,
            OccurredAt = AgentCommandEnvelopeComposer.FormatUtc(occurredAt),
            Producer = producer,
            DeliveryAttempt = 0,
            Payload = JsonSerializer.SerializeToElement(
                new AgentActionResultV1
                {
                    ProposalId = proposalId.ToString("D"),
                    Outcome = outcome,
                    Reason = reason,
                    AppliedArticleRevision = appliedArticleRevision,
                    ValidatedAt = AgentCommandEnvelopeComposer.FormatUtc(validatedAt),
                },
                AgentCommandEnvelopeComposer.SerializerOptions),
        };

        return (JsonSerializer.Serialize(envelope, AgentCommandEnvelopeComposer.SerializerOptions), messageId);
    }

    /// <summary>Ret kararının deterministik message_id'si: aynı (proposal_id, içerik
    /// hash'i, ret) tekrarı aynı kimliği üretir; service outbox varlık kontrolüyle
    /// tek kaydı korur (idempotent ret bildirimi).</summary>
    public static string DeterministicRejectionMessageId(Guid runId, Guid proposalId, string contentHash)
    {
        var name = $"action-result-rejected:{runId:D}:{proposalId:D}:{contentHash}";
        return DeterministicUuid(RejectionNamespace, name).ToString("D");
    }

    /// <summary>RFC 4122 §4.3 (UUIDv5 benzeri) deterministik kimlik: SHA-1 tabanlı;
    /// yalnız ret mesajı tekilleştirmesi için kullanılır.</summary>
    private static Guid DeterministicUuid(Guid namespaceId, string name)
    {
        var namespaceBytes = namespaceId.ToByteArray();
        // Guid byte sırası little-endian karışıktır; RFC ad alanı bayt düzeni için
        // büyük uçlu üç bileşene çevrilir.
        SwapGuidBytes(namespaceBytes);
        var nameBytes = System.Text.Encoding.UTF8.GetBytes(name);
        var hash = SHA1.HashData([.. namespaceBytes, .. nameBytes]);

        var guidBytes = new byte[16];
        Array.Copy(hash, guidBytes, 16);
        SwapGuidBytes(guidBytes);

        guidBytes[7] = (byte)((guidBytes[7] & 0x0F) | 0x50); // sürüm 5
        guidBytes[8] = (byte)((guidBytes[8] & 0x3F) | 0x80); // RFC varyantı
        return new Guid(guidBytes);
    }

    private static void SwapGuidBytes(byte[] bytes)
    {
        Swap(bytes, 0, 3);
        Swap(bytes, 1, 2);
        Swap(bytes, 4, 5);
        Swap(bytes, 6, 7);
    }

    private static void Swap(byte[] bytes, int left, int right) =>
        (bytes[left], bytes[right]) = (bytes[right], bytes[left]);
}
