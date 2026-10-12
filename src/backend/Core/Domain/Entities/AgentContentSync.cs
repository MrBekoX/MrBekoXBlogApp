using BlogApp.Core.Domain.Common;
using BlogApp.Core.Domain.Enums;

namespace BlogApp.Core.Domain.Entities;

/// <summary>
/// Backend'in başlattığı ilk içerik senkronizasyonunun kaydı (plan B8). Watermark,
/// senkron sürerken olan değişikliklerin kaybolmadığının backend tarafındaki
/// kanıtıdır: snapshot anındaki en yüksek content_revision burada saklanır; senkron
/// sırasında gerçekleşen her değişiklik DAHA YÜKSEK revision'lı canlı
/// ArticleContentChangedV1 olayı üretir ve consumer monotonluk kuralıyla (yeni
/// revizyon uygulanır, eski yok sayılır) ikisini de doğru sırayla birleştirir.
/// Tamamlanmamış (Running'de kalmış) senkron kaydı operasyonel görünürlük içindir;
/// consumer tarafı eksik snapshot nedeniyle indeks SİLMEZ (plan B8).
/// </summary>
public class AgentContentSync : BaseAuditableEntity
{
    /// <summary>Senkron kimliği; ContentSnapshotBatchV1.sync_id ve
    /// ContentSnapshotCompletedV1.sync_id bu değerin kanonik UUID metnidir.</summary>
    public Guid SyncId { get; set; }

    /// <summary>Senkronun yürütüldüğü tekil makale kümesinin anlık okuması; canlı
    /// değişiklikler canlı olaylarla taşındığından okuma tutarlılığı statement-level
    /// snapshot'la yeterlidir (Read Committed; PG-ISOLATION#C1).</summary>
    public AgentContentSyncStatus Status { get; set; } = AgentContentSyncStatus.Running;

    /// <summary>Tek outbox batch'ine yazılan en fazla referans sayısı (batch sınırı).</summary>
    public int BatchSize { get; set; }

    /// <summary>Snapshot'taki yayımlanmış makale sayısı; completed mesajının item_count'u budur.</summary>
    public int ItemCount { get; set; }

    /// <summary>Toplam batch sayısı (snapshot boşsa 0; completed mesajı yine gönderilir).</summary>
    public int TotalBatches { get; set; }

    /// <summary>Snapshot anındaki en yüksek content_revision (değişiklik watermark'ı).</summary>
    public long RevisionWatermark { get; set; }

    /// <summary>Senkronun başladığı an (UTC).</summary>
    public DateTime StartedAt { get; set; }

    /// <summary>Senkronun tamamlandığı an (UTC); Running'de null.</summary>
    public DateTime? CompletedAt { get; set; }
}
