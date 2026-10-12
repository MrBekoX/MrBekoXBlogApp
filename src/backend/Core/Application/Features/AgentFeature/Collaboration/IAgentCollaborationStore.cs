using BlogApp.Core.Domain.Entities;

namespace BlogApp.Core.Application.Features.AgentFeature.Collaboration;

/// <summary>
/// İş birliği proposal'ının kalıcı depo soyutlaması (B9). Gerçekleştirim
/// (Infrastructure/EfAgentCollaborationStore) çağrıyı SAHİBİN açtığı transaction'a
/// katılır: onay/resume durum makinesi geçişleri ile outbox kaydı TEK
/// transaction'da atomiktir (B3 outbox deseni).
/// </summary>
public interface IAgentCollaborationStore
{
    /// <summary>Proposal sürümünü kalıcı yazar; aynı (proposal_id, content_hash) tekrarı
    /// no-op'tur (idempotent). Yeni sürümde Version monoton artar.</summary>
    Task<ProposalUpsertResult> UpsertProposalAsync(AgentProposalUpsert upsert, CancellationToken cancellationToken = default);

    /// <summary>Run'ın sahiplik + terminal bilgisi; run yoksa null (sahiplik backend kaydından).</summary>
    Task<CollaborationRunState?> GetRunStateAsync(Guid runId, CancellationToken cancellationToken = default);

    /// <summary>Proposal'ın güncel (en yüksek sürümlü) kaydı; yoksa null.</summary>
    Task<AgentProposalSnapshot?> GetCurrentProposalAsync(Guid runId, Guid proposalId, CancellationToken cancellationToken = default);

    /// <summary>Belirli bir sürüm satırını koşullu olarak 'proposed → confirmed' geçirir:
    /// ``UPDATE ... WHERE Id = @row AND Status = 'proposed'``. Bir satır etkilenmezse
    /// güncel durumu yeniden okuyup kararı verir (aynı hash → Duplicate,
    /// farklı hash → VersionConflict). Eşzamanlı çift onayda TEK çağrı kazanır.</summary>
    Task<ConfirmationTransition> ConfirmAsync(Guid proposalRowId, string contentHash, DateTimeOffset confirmedAt, CancellationToken cancellationToken = default);

    /// <summary>Onaylı satırı koşullu 'confirmed → resume_sent' geçirir; true = bu çağrı
    /// geçişi yaptı (resume mesajı üretilebilir), false = zaten resume_sent (ikinci resume üretilmez).</summary>
    Task<bool> MarkResumeSentAsync(Guid proposalRowId, CancellationToken cancellationToken = default);
}
