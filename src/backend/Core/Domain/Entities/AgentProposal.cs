using BlogApp.Core.Domain.Common;

namespace BlogApp.Core.Domain.Entities;

/// <summary>
/// Agent ActionProposal'ının backend kalıcı kaydı (B9; plan B9: "Proposal kimliği,
/// içerik sürümü/hash'i, run sahipliği ve süre sınırı tut"). Kayıt, agent'ın
/// ``agent.action.proposed`` olayı projection'ı üzerinden yazılır (B5); gönderim
/// onayı YALNIZ açık backend eylemiyle (AgentCollaborationService) alınır — LLM
/// metni veya olayın kendisi onay kaynağı DEĞİLDİR (plan B9).
///
/// Sürüm modeli: aynı ``ProposalId`` birden fazla içerik sürümü taşıyabilir —
/// ziyaretçi düzenlemesi YENİ sürüm üretir (``Version`` monoton artar; plan B9:
/// "Ziyaretçinin düzenlemesini yeni proposal sürümüyle ilişkilendir").
/// ``(ProposalId, ContentHash)`` benzersizdir: aynı sürümün tekrar upsert'i
/// no-op'tur (idempotent projection tekrarları).
///
/// Durum makinesi proposal başına YÜRÜR (en yüksek sürümün satırı geçerli durumu
/// taşır): ``proposed → confirmed → resume_sent``. Aynı onay için ikinci kayıt
/// üretilmez; aynı onay için ikinci resume üretilmez (plan B9).
/// </summary>
public class AgentProposal : BaseAuditableEntity
{
    /// <summary>Surrogate birincil anahtar; sözleşme kimliği ProposalId'dir.</summary>
    public Guid Id { get; set; }

    /// <summary>Agent'ın ürettiği proposal kimliği (AgentActionProposedV1.proposal_id).</summary>
    public Guid ProposalId { get; set; }

    /// <summary>Proposal başına içerik sürümü (1'den başlar; düzenleme yeni sürüm üretir).</summary>
    public long Version { get; set; }

    /// <summary>Sahip run; sahiplik AgentRun.OwnerKey ile eşleşmek zorundadır (plan B9).</summary>
    public Guid RunId { get; set; }

    /// <summary>Önerinin dayandığı makale (AgentActionProposedV1.article_id).</summary>
    public Guid ArticleId { get; set; }

    /// <summary>Önerinin dayandığı makale revizyonu (D008 anlamı); kabul sonucu mesajında
    /// ``applied_article_revision`` olarak döner (A1 ValidatedActionResult kuralı).</summary>
    public long ArticleRevision { get; set; }

    /// <summary>Önerinin dayandığı makale içerik hash'i (D008: UTF-8 SHA-256 hex).</summary>
    public string BaseContentHash { get; set; } = string.Empty;

    /// <summary>Bu sürümün içerik hash'i: backend'in sakladığı düzenlenebilir özet
    /// metninin UTF-8 SHA-256 özeti; onay isteği bu sürüme karşı doğrulanır
    /// ("değiştirilmiş proposal" reddi buradan gelir).</summary>
    public string ContentHash { get; set; } = string.Empty;

    /// <summary>Düzenlenebilir özet metni (ziyaretçiye gösterilen ve düzenlenen içerik).</summary>
    public string Summary { get; set; } = string.Empty;

    /// <summary>Run sahipliğinin kopyası ("u:{userId}" / "g:{guestSession}"); upsert anında
    /// projection'dan yazılır, onay isteğinin owner iddiasıyla karşılaştırılır.</summary>
    public string OwnerKey { get; set; } = string.Empty;

    /// <summary>Süre sınırı (backend politikası): bu zamandan sonra onay reddedilir (plan B9).</summary>
    public DateTimeOffset ExpiresAt { get; set; }

    /// <summary>Durum makinesi: proposed → confirmed → resume_sent (plan B9).</summary>
    public string Status { get; set; } = AgentProposalStatus.Proposed;

    /// <summary>Onay anı ( Accepted kararında yazılır; Duplicate tekrarında değişmez).</summary>
    public DateTimeOffset? ConfirmedAt { get; set; }

    /// <summary>Onayın doğruladığı içerik hash'i; düzenleme sonrası ContentHash'ten
    /// farklı yeni sürümü işaret edebilir (kabul edilen sürümün denetim izi).</summary>
    public string? ConfirmedContentHash { get; set; }
}

/// <summary>AgentProposal durum makinesi değerleri (plan B9: proposed → confirmed → resume_sent).</summary>
public static class AgentProposalStatus
{
    public const string Proposed = "proposed";
    public const string Confirmed = "confirmed";
    public const string ResumeSent = "resume_sent";

    /// <summary>Tanımlı durumlar (migration CHECK kısıtıyla aynı küme).</summary>
    public static readonly string[] All = [Proposed, Confirmed, ResumeSent];
}
