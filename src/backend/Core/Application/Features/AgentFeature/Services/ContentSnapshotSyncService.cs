using BlogApp.Core.Application.Common.Interfaces.Data;
using BlogApp.Core.Application.Common.Interfaces.Messaging;
using BlogApp.Core.Application.Common.Interfaces.Persistence;
using BlogApp.Core.Application.Common.Messaging;
using BlogApp.Core.Application.Common.Options;
using BlogApp.Core.Domain.Entities;
using BlogApp.Core.Domain.Enums;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;

namespace BlogApp.Core.Application.Features.AgentFeature.Services;

/// <summary>İlk senkronizasyonun tek yürütmenin sonucu (raporlama için).</summary>
public sealed record ContentSyncSummary(
    Guid SyncId,
    int ItemCount,
    int TotalBatches,
    int BatchSize,
    long RevisionWatermark);

/// <summary>
/// B8 ilk içerik senkronizasyonu (plan B8): yayımlanmış makalelerin anlık
/// (article_id, article_revision, content_hash) referans kümesini
/// ContentSnapshotBatchV1 batch'lerine bölüp blog.content.events üzerinden
/// agent.content.q'ya (outbox → relay) yazduktan sonra ContentSnapshotCompletedV1
/// ile kapatır.
///
/// Değişiklik watermark'ı: snapshot anındaki en yüksek content_revision
/// <see cref="AgentContentSync.RevisionWatermark"/> olarak kaydedilir. Senkron
/// sürerken olan değişiklikler KAYBOLMAZ: her canlı değişiklik ayrı ve DAHA YÜKSEK
/// revision'lı ArticleContentChangedV1 üretir (aynı handler transaction'ında);
/// consumer monotonluk kuralıyla (yeni revizyon uygulanır, eski yok sayılır)
/// batch referansını ve canlı olayı hangi sırayla gelirse gelsin doğru birleştirir.
///
/// Tamamlanmamış snapshot (ör. backend çökmesiyle completed yazılamadı) consumer
/// tarafında indeks SİLME tetiklemez; agent bilgi tabanı additive kalır (plan B8).
/// </summary>
public sealed class ContentSnapshotSyncService(
    IApplicationDbContext dbContext,
    IUnitOfWork unitOfWork,
    IOutboxWriter outboxWriter,
    IOptions<AgentContentSyncSettings> syncOptions,
    IOptions<AgentMessagingSettings> messagingOptions,
    ILogger<ContentSnapshotSyncService> logger)
{
    public async Task<ContentSyncSummary> RunSyncAsync(CancellationToken cancellationToken = default)
    {
        var batchSize = Math.Max(syncOptions.Value.BatchSize, 1);
        var syncId = Guid.NewGuid();
        var startedAt = DateTime.UtcNow;
        var producer = messagingOptions.Value.ProducerName;

        // Anlık snapshot okuması (Read Committed statement-level tutarlılık; PG-ISOLATION#C1):
        // canlı değişiklikler ayrı canlı olaylarla taşındığından tek sorguluk okuma yeterlidir.
        var snapshot = dbContext.Posts
            .AsNoTracking()
            .Where(p => p.Status == PostStatus.Published)
            .OrderBy(p => p.Id)
            .Select(p => new { p.Id, p.ContentRevision, p.Content })
            .AsAsyncEnumerable();

        // Retain only small reference tuples in application state. The provider
        // may still buffer query rows when transient database retries are enabled.
        var items = new List<(Guid ArticleId, long Revision, string ContentHash)>();
        await foreach (var post in snapshot.WithCancellation(cancellationToken))
        {
            items.Add((post.Id, post.ContentRevision, AgentContentEventComposer.ComputeContentHash(post.Content)));
        }

        var totalBatches = (int)Math.Ceiling(items.Count / (double)batchSize);
        var watermark = items.Count == 0 ? 0 : items.Max(item => item.Revision);

        // Zarflar commit'ten ÖNCE B1 doğrulayıcısından geçer; doğrulama hatası senkronu başlatmadan bitirir.
        var envelopes = new List<(OutboxMessage Message, string MessageType)>(totalBatches + 1);
        for (var batchIndex = 0; batchIndex < totalBatches; batchIndex++)
        {
            var slice = items
                .Skip(batchIndex * batchSize)
                .Take(batchSize)
                .Select(item => (item.ArticleId, item.Revision, item.ContentHash))
                .ToList();

            envelopes.Add(CreateMessage(
                AgentContentEventComposer.ComposeSyncBatch(syncId.ToString("D"), batchIndex, totalBatches, slice, producer),
                AgentMessageTypes.SyncBatch,
                AgentMessageTypeRegistry.RoutingKeyFor(AgentMessageTypeRegistry.ContentSchemaVersion, AgentMessageTypes.SyncBatch)));
        }

        envelopes.Add(CreateMessage(
            AgentContentEventComposer.ComposeSyncCompleted(syncId.ToString("D"), items.Count, producer),
            AgentMessageTypes.SyncCompleted,
            AgentMessageTypeRegistry.RoutingKeyFor(AgentMessageTypeRegistry.ContentSchemaVersion, AgentMessageTypes.SyncCompleted)));

        var syncRecord = new AgentContentSync
        {
            SyncId = syncId,
            Status = AgentContentSyncStatus.Completed,
            BatchSize = batchSize,
            ItemCount = items.Count,
            TotalBatches = totalBatches,
            RevisionWatermark = watermark,
            StartedAt = startedAt,
            CompletedAt = DateTime.UtcNow,
        };

        // Senkron kaydı + tüm batch'ler + completed kaydı TEK transaction'da (tek SaveChanges);
        // yarım senkron outbox'ta görünmez — eksik snapshot yalnız gerçek çökme senaryolarında
        // (commit öncesi) oluşur ve consumer'da indeks silme tetiklemez.
        await dbContext.AgentContentSyncs.AddAsync(syncRecord, cancellationToken);
        foreach (var (message, _) in envelopes)
        {
            await outboxWriter.AddAsync(message, cancellationToken);
        }
        await unitOfWork.SaveChangesAsync(cancellationToken);

        logger.LogInformation(
            "[AgentContentSync] senkron {SyncId} tamamlandı: item={ItemCount} batch={TotalBatches} watermark={Watermark}",
            syncId, items.Count, totalBatches, watermark);

        return new ContentSyncSummary(syncId, items.Count, totalBatches, batchSize, watermark);
    }

    private static (OutboxMessage Message, string MessageType) CreateMessage(
        (string EnvelopeJson, string MessageId) composed,
        string messageType,
        string routingKey)
    {
        var envelope = new AgentContractValidator().Validate(composed.EnvelopeJson);
        if (!envelope.IsValid)
        {
            throw new InvalidOperationException(
                $"İçerik senkron zarfı sözleşme doğrulamasını geçemedi ({messageType}, {envelope.Error?.Field}: {envelope.Error?.Message}).");
        }

        return (new OutboxMessage
        {
            MessageId = composed.MessageId,
            MessageType = messageType,
            Exchange = AgentMessageTypeRegistry.ContentExchange,
            RoutingKey = routingKey,
            CorrelationId = composed.MessageId,
            EnvelopeJson = composed.EnvelopeJson,
            Status = AgentOutboxStatus.Pending,
        }, messageType);
    }
}
