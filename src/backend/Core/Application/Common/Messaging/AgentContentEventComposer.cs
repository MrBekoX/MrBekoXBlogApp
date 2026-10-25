using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace BlogApp.Core.Application.Common.Messaging;

/// <summary>
/// B8 içerik olayı zarfları (ArticleContentChangedV1, ContentSnapshotBatchV1,
/// ContentSnapshotCompletedV1, ProfileContentChangedV1, ProjectContentChangedV1).
/// B1 sözleşmesi DONUKTUR: content.article.changed gövdesi yalnız
/// article_id/article_revision/action/content_hash/language/title taşır — içerik
/// GÖMÜLMEZ (K7). Plan B8'in "status" öğesi action enum'una (updated = yayımlanmış
/// içerik anı, unpublished = kaldırma tombstone'u), "canonical URL" ve
/// "yayınlanmış snapshot" öğeleri referans anlambilmine (çalışma anında kabul
/// snapshot'ındaki slug + consumer canonical_url_template'i) karşılık gelir.
/// message_id outbox tekrar yayınında korunur (plan satır 301).
/// </summary>
public static class AgentContentEventComposer
{
    /// <summary>Makale içeriğinin UTF-8 SHA-256 özeti (D008: article_content_hash tanımı).</summary>
    public static string ComputeContentHash(string content) =>
        Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(content ?? string.Empty))).ToLowerInvariant();

    /// <summary>Yayımlanmış içerik anı güncellemesi (action=updated); content_hash zorunludur.</summary>
    public static (string EnvelopeJson, string MessageId) ComposeArticleChanged(
        Guid articleId,
        long articleRevision,
        string action,
        string? contentHash,
        string? language,
        string? title,
        string producer,
        string? correlationId = null)
    {
        var messageId = Guid.NewGuid().ToString("D");

        var envelope = new AgentEnvelope
        {
            MessageId = messageId,
            MessageType = AgentMessageTypes.ArticleContentChanged,
            SchemaVersion = AgentMessageTypeRegistry.ContentSchemaVersion,
            CorrelationId = correlationId ?? messageId,
            OccurredAt = AgentCommandEnvelopeComposer.FormatUtc(DateTimeOffset.UtcNow),
            Producer = producer,
            TraceContext = AgentTraceContext.Capture(),
            DeliveryAttempt = 0,
            Payload = JsonSerializer.SerializeToElement(
                new ArticleContentChangedV1
                {
                    ArticleId = articleId.ToString("D"),
                    ArticleRevision = articleRevision,
                    Action = action,
                    ContentHash = contentHash,
                    Language = language,
                    Title = title,
                },
                AgentCommandEnvelopeComposer.SerializerOptions),
        };

        return (JsonSerializer.Serialize(envelope, AgentCommandEnvelopeComposer.SerializerOptions), messageId);
    }

    /// <summary>İlk senkronizasyon toplu referans paketi (K7: yalnız (article_id, revision, hash)).</summary>
    public static (string EnvelopeJson, string MessageId) ComposeSyncBatch(
        string syncId,
        long batchIndex,
        long totalBatches,
        IReadOnlyList<(Guid ArticleId, long ArticleRevision, string ContentHash)> items,
        string producer,
        string? correlationId = null)
    {
        var messageId = Guid.NewGuid().ToString("D");

        var envelope = new AgentEnvelope
        {
            MessageId = messageId,
            MessageType = AgentMessageTypes.SyncBatch,
            SchemaVersion = AgentMessageTypeRegistry.ContentSchemaVersion,
            CorrelationId = correlationId ?? messageId,
            OccurredAt = AgentCommandEnvelopeComposer.FormatUtc(DateTimeOffset.UtcNow),
            Producer = producer,
            TraceContext = AgentTraceContext.Capture(),
            DeliveryAttempt = 0,
            Payload = JsonSerializer.SerializeToElement(
                new ContentSnapshotBatchV1
                {
                    SyncId = syncId,
                    BatchIndex = batchIndex,
                    TotalBatches = totalBatches,
                    Items = items
                        .Select(item => new AgentContentReference
                        {
                            ArticleId = item.ArticleId.ToString("D"),
                            ArticleRevision = item.ArticleRevision,
                            ContentHash = item.ContentHash,
                        })
                        .ToList(),
                },
                AgentCommandEnvelopeComposer.SerializerOptions),
        };

        return (JsonSerializer.Serialize(envelope, AgentCommandEnvelopeComposer.SerializerOptions), messageId);
    }

    /// <summary>İlk senkronizasyonun tamamlandığı işareti; sync_id batch'lerle aynıdır.</summary>
    public static (string EnvelopeJson, string MessageId) ComposeSyncCompleted(
        string syncId,
        long itemCount,
        string producer,
        string? correlationId = null)
    {
        var messageId = Guid.NewGuid().ToString("D");

        var envelope = new AgentEnvelope
        {
            MessageId = messageId,
            MessageType = AgentMessageTypes.SyncCompleted,
            SchemaVersion = AgentMessageTypeRegistry.ContentSchemaVersion,
            CorrelationId = correlationId ?? messageId,
            OccurredAt = AgentCommandEnvelopeComposer.FormatUtc(DateTimeOffset.UtcNow),
            Producer = producer,
            TraceContext = AgentTraceContext.Capture(),
            DeliveryAttempt = 0,
            Payload = JsonSerializer.SerializeToElement(
                new ContentSnapshotCompletedV1
                {
                    SyncId = syncId,
                    ItemCount = itemCount,
                },
                AgentCommandEnvelopeComposer.SerializerOptions),
        };

        return (JsonSerializer.Serialize(envelope, AgentCommandEnvelopeComposer.SerializerOptions), messageId);
    }

    /// <summary>Onaylı profil içeriği değişti (ayrı sürümlenmiş içerik olayı).</summary>
    public static (string EnvelopeJson, string MessageId) ComposeProfileChanged(
        long profileRevision,
        string contentHash,
        string producer,
        string? contextSnapshotReference = null,
        string? correlationId = null)
    {
        var messageId = Guid.NewGuid().ToString("D");

        var envelope = new AgentEnvelope
        {
            MessageId = messageId,
            MessageType = AgentMessageTypes.ProfileContentChanged,
            SchemaVersion = AgentMessageTypeRegistry.ContentSchemaVersion,
            CorrelationId = correlationId ?? messageId,
            OccurredAt = AgentCommandEnvelopeComposer.FormatUtc(DateTimeOffset.UtcNow),
            Producer = producer,
            TraceContext = AgentTraceContext.Capture(),
            DeliveryAttempt = 0,
            Payload = JsonSerializer.SerializeToElement(
                new ProfileContentChangedV1
                {
                    ProfileRevision = profileRevision,
                    ContentHash = contentHash,
                    ContextSnapshotReference = contextSnapshotReference,
                },
                AgentCommandEnvelopeComposer.SerializerOptions),
        };

        return (JsonSerializer.Serialize(envelope, AgentCommandEnvelopeComposer.SerializerOptions), messageId);
    }

    /// <summary>Onaylı proje rehberi değişti (ayrı sürümlenmiş içerik olayı).</summary>
    public static (string EnvelopeJson, string MessageId) ComposeProjectChanged(
        Guid projectId,
        long projectRevision,
        string contentHash,
        string producer,
        string? contextSnapshotReference = null,
        string? correlationId = null)
    {
        var messageId = Guid.NewGuid().ToString("D");

        var envelope = new AgentEnvelope
        {
            MessageId = messageId,
            MessageType = AgentMessageTypes.ProjectContentChanged,
            SchemaVersion = AgentMessageTypeRegistry.ContentSchemaVersion,
            CorrelationId = correlationId ?? messageId,
            OccurredAt = AgentCommandEnvelopeComposer.FormatUtc(DateTimeOffset.UtcNow),
            Producer = producer,
            TraceContext = AgentTraceContext.Capture(),
            DeliveryAttempt = 0,
            Payload = JsonSerializer.SerializeToElement(
                new ProjectContentChangedV1
                {
                    ProjectId = projectId.ToString("D"),
                    ProjectRevision = projectRevision,
                    ContentHash = contentHash,
                    ContextSnapshotReference = contextSnapshotReference,
                },
                AgentCommandEnvelopeComposer.SerializerOptions),
        };

        return (JsonSerializer.Serialize(envelope, AgentCommandEnvelopeComposer.SerializerOptions), messageId);
    }
}
