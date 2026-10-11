namespace BlogApp.Core.Application.Common.Options;

/// <summary>
/// Outbox relay (publisher hosted service) ayarları — appsettings "AgentOutbox" section (B3).
/// Kayıtclaim + confirm zaman aşımı + geri çekilme (lease ile doğal backoff) buradan yönetilir.
/// </summary>
public sealed class AgentOutboxRelaySettings
{
    public const string SectionName = "AgentOutbox";

    /// <summary>Tek döngüde claim edilecek kayıt üst sınırı.</summary>
    public int BatchSize { get; set; } = 16;

    /// <summary>Bekleyen kayıt yokken iki tarama arası bekleme (saniye).</summary>
    public int PollIntervalSeconds { get; set; } = 2;

    /// <summary>Temel lease süresi (saniye); deneme sayısıyla üstel büyür, MaxClaimLeaseSeconds ile sınırlıdır.
    /// Confirm alınamayan kayıt bu süre boyunca beklemede kalır (plan satır 300).</summary>
    public int ClaimLeaseSeconds { get; set; } = 60;

    public int MaxClaimLeaseSeconds { get; set; } = 600;

    /// <summary>Tek yayının confirm bekleme zaman aşımı (saniye); aşılırsa kayıt beklemede bırakılır
    /// ve aynı message_id ile tekrar yayınlanır (plan satır 301).</summary>
    public int ConfirmTimeoutSeconds { get; set; } = 10;

    /// <summary>Bu üst sınıra ulaşan kayıt DeadLettered olur; sonsuz tekrar üretmez (main prompt:
    /// retry/DLQ kör ve sınırsız tekrar çalıştırma üretmez).</summary>
    public int MaxAttempts { get; set; } = 12;

    /// <summary>Publisher instance kimliği (outbox kaydında ClaimedBy); çoklu publisher ayırt edilir.</summary>
    public string InstanceName { get; set; } = "backend-outbox";
}
