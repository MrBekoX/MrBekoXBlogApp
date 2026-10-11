using BlogApp.Core.Domain.Common;
using BlogApp.Core.Domain.Enums;

namespace BlogApp.Core.Domain.Entities;

/// <summary>
/// Transactional outbox kaydı (plan satır 295-303): iş verisiyle AYNI transaction'da yazılır,
/// ayrı bir relay (publisher hosted service) confirm bekleyerek yayınlar. Güvenilirlik kaynağı
/// DB'dir: commit sonrası broker kapansa bile kayıt kalır ve tekrar yayınlanır.
/// </summary>
public class OutboxMessage : BaseAuditableEntity
{
    /// <summary>Zarf message_id; broker'a tekrar yayınlamada KORUNUR (plan satır 301: kayıp
    /// confirm aynı message_id ile yeniden yayınlanır; consumer inbox bu kimlikle tekilleştirir).</summary>
    public string MessageId { get; set; } = string.Empty;

    public string MessageType { get; set; } = string.Empty;

    public string Exchange { get; set; } = string.Empty;

    public string RoutingKey { get; set; } = string.Empty;

    public string CorrelationId { get; set; } = string.Empty;

    /// <summary>Komut bir agent run'ına aitse run referansı (izleme/temizlik sorguları için).</summary>
    public Guid? RunId { get; set; }

    /// <summary>Tam zarf JSON'u; byte-exact tekrar yayın için saklanır (delivery_attempt hariç —
    /// her denemede transport tekrar sayacı güncellenir, message_id korunur).</summary>
    public string EnvelopeJson { get; set; } = string.Empty;

    public AgentOutboxStatus Status { get; set; } = AgentOutboxStatus.Pending;

    /// <summary>Kaydı lease ile alan publisher instance kimliği (çoklu publisher'ın aynı kaydı
    /// almasını engeller; FOR UPDATE SKIP LOCKED ile birlikte).</summary>
    public string? ClaimedBy { get; set; }

    public DateTime? ClaimedAt { get; set; }

    /// <summary>Lease bitişi; süresi geçen Claimed kayıt yeniden alınabilir (publisher çökerse
    /// kayıt kaybolmaz, beklemede kalır).</summary>
    public DateTime? ClaimLeaseUntil { get; set; }

    /// <summary>Yayın deneme sayacı; zarf delivery_attempt alanına yazılır (ilk yayında 0).
    /// Transport tekrarı ile agent yürütme denemesi (execution_attempt) ayrı alanlardır.</summary>
    public int AttemptCount { get; set; }

    public string? LastError { get; set; }

    public DateTime? LastAttemptAt { get; set; }

    public DateTime? PublishedAt { get; set; }
}
