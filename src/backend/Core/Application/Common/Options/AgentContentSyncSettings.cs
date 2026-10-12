namespace BlogApp.Core.Application.Common.Options;

/// <summary>
/// B8 ilk içerik senkronizasyonu ayarları (plan B8: "İlk senkronizasyonu backend'in
/// başlattığı ContentSnapshotBatchV1 ve ContentSnapshotCompletedV1 mesajlarıyla uygula").
/// Varsayılanda kapalıdır: senkronu tetikleme zamanı operasyonel karardır (B10/B11
/// hosted-service bağlaması); servis DI üzerinden test ve operasyon için hazırdır.
/// </summary>
public sealed class AgentContentSyncSettings
{
    public const string SectionName = "AgentContentSync";

    /// <summary>Tek outbox batch'ine yazılan en fazla (article_id, revision, hash) referansı.
    /// Batch sınırı K7 zarf üst sınırıyla birlikte çalışır: 256 KiB zarf sınırına takılmamak
    /// için referans paketleri küçük tutulur.</summary>
    public int BatchSize { get; set; } = 50;

    /// <summary>Uygulama açılışında otomatik senkron tetikleyicisi (B10/B11 hosted bağlaması
    /// için ayrılmıştır; bu fazda tetik zamanı operasyoneldir).</summary>
    public bool Enabled { get; set; }
}
