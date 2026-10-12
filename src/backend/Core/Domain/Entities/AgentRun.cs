using BlogApp.Core.Domain.Common;
using BlogApp.Core.Domain.Enums;

namespace BlogApp.Core.Domain.Entities;

/// <summary>
/// Bir agent çalıştırmasının backend kabul kaydı (plan satır 291-293):
/// run_id + turn_sequence + immutable bağlam snapshot'ı; komut outbox kaydıyla
/// TEK transaction'da yazılır. ``Id`` alanı sözleşmedeki run_id'nin ta kendisidir
/// (kanonik UUID). Sahiplik backend tarafından yazılır; istemcinin gönderdiği
/// owner alanı yetki kaynağı değildir (plan satır 124, K5).
/// </summary>
public class AgentRun : BaseAuditableEntity
{
    /// <summary>Ait olduğu konuşma; turn_sequence bu konuşma içinde monoton artar.</summary>
    public Guid ConversationId { get; set; }

    /// <summary>Konuşma içindeki sıra (1'den başlar); (ConversationId, TurnSequence) benzersizdir.</summary>
    public long TurnSequence { get; set; }

    /// <summary>Sahip kimliği anahtarı: "u:{userId}" veya "g:{guestSessionId}"; idempotency ve
    /// limit sorgularının tek sütunla çalışmasını sağlar (nullable kullanıcı sütunu unique
    /// index'te Postgres NULL-distinct sorununa yol açar).</summary>
    public string OwnerKey { get; set; } = string.Empty;

    /// <summary>Oturum doğrulaması JWT'den çözümlenmiş kullanıcı; misafirde null.</summary>
    public Guid? OwnerUserId { get; set; }

    /// <summary>Sunucu tarafı misafir oturum kimliği (K5: HttpOnly cookie, Presentation üretir); kullanıcıda null.</summary>
    public string? GuestSessionId { get; set; }

    /// <summary>İstemcinin verdiği idempotency anahtarı; (OwnerKey, IdempotencyKey) benzersizdir.</summary>
    public string IdempotencyKey { get; set; } = string.Empty;

    /// <summary>Anahtarın karşılaştırıldığı payload özeti (SHA-256 hex); aynı anahtar farklı
    /// payload ile gelirse kabul çakışma ile reddedilir (plan satır 290).</summary>
    public string IdempotencyPayloadHash { get; set; } = string.Empty;

    /// <summary>Backend kabul durumu; olay tabanlı geçişler B5 projection'ındadır.</summary>
    public AgentRunStatus Status { get; set; } = AgentRunStatus.Accepted;

    public string Question { get; set; } = string.Empty;

    public string Language { get; set; } = string.Empty;

    public string ModePreference { get; set; } = string.Empty;

    public string BudgetProfile { get; set; } = string.Empty;

    /// <summary>Soru bir makale bağlamında sorulduysa makale referansı; erişim kontrolü kabulde yapılır.</summary>
    public Guid? ArticleId { get; set; }

    /// <summary>Kabul anındaki makale içeriğinin UTF-8 SHA-256 özeti (D008); BlogPost.Version
    /// (xmin rowversion) revizyon anlamı taşımaz ve BURADA KULLANILMAZ (L004).</summary>
    public string? ArticleContentHash { get; set; }

    /// <summary>Immutable bağlam snapshot'ının referansı; payload'taki context_snapshot_reference
    /// alanına aynen kopyalanır (K7: makale içeriği mesaja gömülmez).</summary>
    public string ContextSnapshotReference { get; set; } = string.Empty;

    /// <summary>Immutable bağlam snapshot'ı (JSON): kabul anındaki makale özeti + soru bağlamı.
    /// Sonradan değiştirilmez; makale güncellenirse yeni run yeni snapshot alır.</summary>
    public string ContextSnapshotJson { get; set; } = string.Empty;

    /// <summary>Backend'in atadığı iş bitiş zamanı (K6: deadline sahibi backend); zarf deadline_at'a yazılır.</summary>
    public DateTime DeadlineAt { get; set; }

    /// <summary>Backend'in sorumluluğu aldığı an (kabul durumuyla Python accepted olayı ayrı anlamlar).</summary>
    public DateTime AcceptedAt { get; set; }

    // ---- B5 projection kolonları (ADDITIVE; migration AddAgentEventInbox ile gelir) ----

    /// <summary>Projection'ın uyguladığı en büyük payload event_sequence'i (run başına monoton).
    /// Gerileme koruması DB'de budur: sequence <= bu değer gelen olay uygulanmaz (B5).</summary>
    public long LastEventSequence { get; set; }

    /// <summary>agent.run.mode_selected olayından kesinleşen mod; henüz seçilmediyse null.</summary>
    public string? SelectedMode { get; set; }

    /// <summary>Terminal sonucun source_scope değeri (completed/partially_completed); diğer olaylarda null.</summary>
    public string? SourceScope { get; set; }

    /// <summary>Terminal olayın tam sonuç snapshot'ı (payload JSON); terminal olmayan olayda null.
    /// Plan B5: "Terminal olay tam sonuç snapshot'ı taşısın; eksik bir ilerleme olayı
    /// tamamlanmayı engellemesin" — snapshot burada kalıcıdır (B10 replay için).</summary>
    public string? ResultJson { get; set; }

    /// <summary>Terminal olayın zarf occurred_at değeri (UTC); terminal olmayan olayda null.</summary>
    public DateTime? TerminalAt { get; set; }
}
