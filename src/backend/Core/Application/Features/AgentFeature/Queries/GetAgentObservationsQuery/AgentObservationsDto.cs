using MediatR;
using BlogApp.Core.Application.Common.Models;

namespace BlogApp.Core.Application.Features.AgentFeature.Queries.GetAgentObservationsQuery;

/// <summary>GET /api/v1/agent/admin/observations isteği (B10; plan admin listesi).
/// Yetki endpoint'te Admin rolüyle sınırlandırılır; handler kimlik sorgulamaz.</summary>
public sealed record GetAgentObservationsQueryRequest : IRequest<Result<AgentObservationsDto>>
{
    /// <summary>Gözlem penceresi (saat); iş süreleri/latency dağılımları bu pencerede hesaplanır.</summary>
    public int WindowHours { get; init; } = 24;
}

/// <summary>Yönetim gözlem anlık görüntüsü; tüm değerler mevcut projection/outbox
/// tablolarından ve (varsa) agent şemasındaki iş kayıtlarından OKUMA ile üretilir;
/// yeni ağır altyapı kurulmaz (plan B10 admin bölümü).</summary>
public sealed record AgentObservationsDto
{
    public required DateTimeOffset GeneratedAt { get; init; }

    public required int WindowHours { get; init; }

    /// <summary>Kabul edilmiş (çözümlenmemiş) iş backlog'u + en eski iş yaşı.</summary>
    public required AgentAcceptanceObservationsDto Acceptance { get; init; }

    /// <summary>Backend outbox: yayın gecikmesi, confirm/attempt hataları, DLQ.</summary>
    public required AgentOutboxObservationsDto Outbox { get; init; }

    /// <summary>Olay projection'ı: duplicate/stale/quarantined sayıları (plan: duplicate/inbox).</summary>
    public required AgentProjectionObservationsDto Projection { get; init; }

    /// <summary>İş süreleri, mod dağılımı, iptal gecikmesi, kalite sinyalleri.</summary>
    public required AgentRunsObservationsDto Runs { get; init; }

    /// <summary>Geri bildirim özeti (B10 feedback kayıtlarından).</summary>
    public required AgentFeedbackObservationsDto Feedback { get; init; }

    /// <summary>Python agent şeması iş kayıtları (queue backlog, lease recovery, retry/DLQ
    /// derinlik vekilleri); şema/tablo yoksa null döner (hata değil — B4 öncesi boş ortam).</summary>
    public AgentJobsObservationsDto? Jobs { get; init; }
}

public sealed record AgentAcceptanceObservationsDto
{
    /// <summary>Status=Accepted (çözümlenmemiş) run sayısı — iş kabul backlog'u.</summary>
    public required int ActiveRuns { get; init; }

    /// <summary>En eski Accepted run'ın yaşı (dakika); backlog boşsa null.</summary>
    public double? OldestActiveRunAgeMinutes { get; init; }

    public required int RunsLastWindow { get; init; }
}

public sealed record AgentOutboxObservationsDto
{
    public required int Pending { get; init; }

    public required int Claimed { get; init; }

    public required int Published { get; init; }

    /// <summary>Deneme üst sınırını aşan kayıtlar (DLQ karşılığı, plan satır 419).</summary>
    public required int DeadLettered { get; init; }

    /// <summary>En eski Pending kaydın yaşı (dakika) — yayın gecikmesi sinyali.</summary>
    public double? OldestPendingAgeMinutes { get; init; }

    /// <summary>Penceredeki yayınlanmış kayıtlar için ortalama kabul→confirm gecikmesi (saniye).</summary>
    public double? AveragePublishLatencySeconds { get; init; }

    /// <summary>Pencerede p95 kabul→confirm gecikmesi (saniye).</summary>
    public double? P95PublishLatencySeconds { get; init; }

    /// <summary>Pencerede en az bir transport tekrarı yaşamış (attempt>0 veya LastError) kayıt sayısı.</summary>
    public required int RecordsWithPublishErrors { get; init; }

    /// <summary>Penceredeki toplam yayın denemesi (message başına attempt toplamı).</summary>
    public required int AttemptSum { get; init; }
}

public sealed record AgentProjectionObservationsDto
{
    public required int Applied { get; init; }

    /// <summary>Tekrar teslimde YENİDEN UYGULANMAYAN olay kayıtları (inbox duplicate idempotency).</summary>
    public required int Duplicates { get; init; }

    /// <summary>Sıra gerilemesi / terminal sonrası eski olay kayıtları.</summary>
    public required int Stale { get; init; }

    /// <summary>Bilinmeyen run karantina kayıtları.</summary>
    public required int Quarantined { get; init; }
}

public sealed record AgentRunsObservationsDto
{
    /// <summary>Pencerede terminalleşen run'ların ortalama kabul→terminal süresi (saniye).</summary>
    public double? AverageRunSeconds { get; init; }

    public double? MaxRunSeconds { get; init; }

    /// <summary>İptal isteminden terminal cancelled'a ortalama gecikme (saniye).</summary>
    public double? AverageCancelLatencySeconds { get; init; }

    public required IReadOnlyDictionary<string, int> ModeCounts { get; init; }

    /// <summary>Terminal dağılımı (Completed/PartiallyCompleted/Failed/Cancelled).</summary>
    public required IReadOnlyDictionary<string, int> TerminalCounts { get; init; }

    /// <summary>Sonucu needs_input sorusuyla bitmemiş sayılan pencere içi terminal sonuç oranı
    /// için ham sayı: unresolved_questions taşıyan tamamlanmış sonuçlar (kalite sinyali).</summary>
    public required int CompletedWithUnresolvedQuestions { get; init; }
}

public sealed record AgentFeedbackObservationsDto
{
    public required int Total { get; init; }

    public double? AverageRating { get; init; }

    public required IReadOnlyDictionary<int, int> RatingCounts { get; init; }
}

public sealed record AgentJobsObservationsDto
{
    /// <summary>Queue sınıfına göre bekleyen (accepted/queued) iş sayısı (plan: queue/job backlog).</summary>
    public required IReadOnlyDictionary<string, int> BacklogByQueue { get; init; }

    /// <summary>En eski bekleyen işin yaşı (dakika).</summary>
    public double? OldestBacklogAgeMinutes { get; init; }

    /// <summary>Lease'i süresi geçmiş running işler — recovery adayı (plan: lease recovery).</summary>
    public required int ExpiredLeaseRunning { get; init; }

    public required IReadOnlyDictionary<string, int> StatusCounts { get; init; }

    /// <summary>Bekleyen retry kuyruğu vekili: pencerede en az bir deneme yaşamış terminal olmayan işler.</summary>
    public required int JobsWithRetries { get; init; }
}
