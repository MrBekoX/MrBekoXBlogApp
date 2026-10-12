namespace BlogApp.Core.Domain.Enums;

/// <summary>
/// Backend'in başlattığı ilk içerik senkronizasyonunun yaşam durumu (plan B8:
/// "İlk senkronizasyonu backend'in başlattığı ContentSnapshotBatchV1 ve
/// ContentSnapshotCompletedV1 mesajlarıyla uygula").
/// </summary>
public enum AgentContentSyncStatus
{
    /// <summary>Senkron başladı; batch'ler outbox'a yazılıyor.</summary>
    Running = 0,

    /// <summary>Tüm batch'ler ve completed kaydı outbox'a yazıldı (commit sonrası broker
    /// teslimi ayrı relay sorumluluğudur; durum DB perspektifinden tamamlanmadır).</summary>
    Completed = 1,
}
