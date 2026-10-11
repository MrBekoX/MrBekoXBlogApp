using System.Diagnostics;
using System.Diagnostics.Metrics;

namespace BlogApp.Infrastructure.Messaging;

/// <summary>
/// Outbox yayın ölçümleri (plan satır 303: outbox yaşı, denemeleri ve yayın hataları ölçülür).
/// Meter adı BuildingBlocks konvansiyonuyla uyumludur (ör. "BlogApp.Cache").
/// </summary>
public static class OutboxMetrics
{
    public const string MeterName = "BlogApp.Outbox";

    private static readonly Meter Meter = new(MeterName);

    /// <summary>Lease ile alınan kayıt sayacı.</summary>
    public static readonly Counter<long> Claimed = Meter.CreateCounter<long>("outbox.claimed");

    /// <summary>Confirm ile tamamlanan yayın sayacı.</summary>
    public static readonly Counter<long> Published = Meter.CreateCounter<long>("outbox.published");

    /// <summary>Başarısız yayın denemeleri (unroutable, confirm zaman aşımı, broker hatası).</summary>
    public static readonly Counter<long> PublishFailed = Meter.CreateCounter<long>("outbox.publish_failed");

    /// <summary>Deneme üst sınırına ulaşan kayıtlar.</summary>
    public static readonly Counter<long> DeadLettered = Meter.CreateCounter<long>("outbox.deadlettered");

    /// <summary>Confirm geldi ama kayıt artık bu publisher'a ait değil (lease yeniden alınmış).</summary>
    public static readonly Counter<long> StaleConfirm = Meter.CreateCounter<long>("outbox.stale_confirm");

    /// <summary>Yayın anında kaydın kabulden bu yana yaşı (saniye).</summary>
    public static readonly Histogram<double> AgeSeconds = Meter.CreateHistogram<double>("outbox.age_seconds", unit: "s");

    /// <summary>Başarılı yayın anındaki deneme sayısı.</summary>
    public static readonly Histogram<long> Attempts = Meter.CreateHistogram<long>("outbox.attempts");
}
