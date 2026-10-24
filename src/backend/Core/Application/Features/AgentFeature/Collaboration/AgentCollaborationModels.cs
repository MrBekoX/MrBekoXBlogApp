namespace BlogApp.Core.Application.Features.AgentFeature.Collaboration;

/// <summary>
/// Projection'ın AgentActionProposedV1'den ürettiği kalıcı proposal upsert'i (B9).
/// Sözleşmedeki altı alan (run_id, proposal_id, content_hash, summary, owner_key,
/// expires_at) + makale üçlüsü: kabul sonucu mesajının zorunlu
/// ``applied_article_revision`` alanı (donuk B1 allOf kuralı) ve B10 görüntüleme
/// bağlamı ancak olayın makale kimliğiyle kurulabilir — bu yüzden upsert kaydı
/// makale alanlarını da taşır (raporda gerekçelendi).
/// </summary>
public sealed record AgentProposalUpsert(
    Guid RunId,
    Guid ProposalId,
    string ContentHash,
    string Summary,
    string OwnerKey,
    DateTimeOffset ExpiresAt,
    Guid ArticleId,
    long ArticleRevision,
    string BaseContentHash);

/// <summary>Upsert sonucu: aynı (proposal_id, content_hash) tekrarı no-op'tur (idempotent).</summary>
public enum ProposalUpsertOutcome
{
    Created,
    AlreadyPresent,
}

public sealed record ProposalUpsertResult(ProposalUpsertOutcome Outcome, long Version);

/// <summary>Run'ın iş birliği kararları için gereken backend durumu (sahiplik kaynağı backend'dir).</summary>
public sealed record CollaborationRunState(
    Guid RunId,
    Guid ConversationId,
    string OwnerKey,
    bool IsTerminal,
    DateTime DeadlineAt,
    int WireVersion = 1);

/// <summary>Proposal'ın güncel (en yüksek sürümlü) kaydının okuma görünümü.</summary>
public sealed record AgentProposalSnapshot(
    Guid RowId,
    Guid ProposalId,
    long Version,
    Guid RunId,
    Guid ArticleId,
    long ArticleRevision,
    string BaseContentHash,
    string ContentHash,
    string Summary,
    string OwnerKey,
    DateTimeOffset ExpiresAt,
    string Status,
    DateTimeOffset? ConfirmedAt,
    string? ConfirmedContentHash);

/// <summary>Onay geçişi sonucu (atomik koşullu UPDATE'in okuması).</summary>
public enum ConfirmationTransition
{
    /// <summary>Koşullu UPDATE satır etkiledi: bu çağrı onayı kaydetti.</summary>
    Confirmed,

    /// <summary>Satır zaten onaylıydı ve içerik hash'i aynı: idempotent Duplicate.</summary>
    Duplicate,

    /// <summary>Satır onaylı ama farklı sürüm onaylanmak istendi: sürüm çatışması.</summary>
    VersionConflict,
}

/// <summary>Gönderim onayı sonucu (entegrasyon sahibi sözleşmesi):
/// Accepted | Duplicate | RejectedOwner | RejectedVersion + kayıt anı.</summary>
public enum CollaborateSubmitOutcome
{
    Accepted,
    Duplicate,
    RejectedOwner,
    RejectedVersion,
}

public sealed record CollaborateSubmitResult(
    CollaborateSubmitOutcome Outcome,
    DateTimeOffset RegisteredAt,
    long Version,
    string? RejectionReason = null)
{
    public bool Accepted => Outcome == CollaborateSubmitOutcome.Accepted;
    public bool Duplicate => Outcome == CollaborateSubmitOutcome.Duplicate;
}

/// <summary>Resume isteği sonucu: aynı onay için ikinci resume ÜRETİLMEZ (Duplicate).</summary>
public enum CollaborateResumeOutcome
{
    Sent,
    Duplicate,
    RejectedOwner,
    RejectedVersion,
}

public sealed record CollaborateResumeResult(
    CollaborateResumeOutcome Outcome,
    DateTimeOffset SentAt,
    string? RejectionReason = null)
{
    public bool Sent => Outcome == CollaborateResumeOutcome.Sent;
    public bool Duplicate => Outcome == CollaborateResumeOutcome.Duplicate;
}
