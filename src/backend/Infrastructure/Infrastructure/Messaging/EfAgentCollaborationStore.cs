using BlogApp.Core.Application.Features.AgentFeature.Collaboration;
using BlogApp.Core.Domain.Entities;
using BlogApp.Core.Domain.Enums;
using BlogApp.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;
using Npgsql;

namespace BlogApp.Infrastructure.Messaging;

/// <summary>
/// <see cref="IAgentCollaborationStore"/> gerçekleştirim (B9): çağrı, sahibinin
/// (AgentCollaborationService / AgentRunEventProjectionHandler) açtığı transaction'a
/// katılır — onay/resume geçişi ile outbox kaydı AYNI transaction'da atomiktir
/// (B3 outbox deseni). Durum makinesi geçişleri koşullu UPDATE'lerle yazılır:
/// eşzamanlı çift onay/çift resume yarışında TEK çağrı satır etkiler (plan B9
/// kabul ölçütleri: çift tıklama, dağıtık yarış).
/// </summary>
public sealed class EfAgentCollaborationStore(AppDbContext context) : IAgentCollaborationStore
{
    /// <summary>Postgres unique ihlali (23505): idempotent upsert yarışının normal yolu.</summary>
    private const string UniqueViolationSqlState = "23505";

    public async Task<ProposalUpsertResult> UpsertProposalAsync(AgentProposalUpsert upsert, CancellationToken cancellationToken = default)
    {
        var existing = await FindRowAsync(upsert.ProposalId, upsert.ContentHash, cancellationToken);
        if (existing is not null)
        {
            return new ProposalUpsertResult(ProposalUpsertOutcome.AlreadyPresent, existing.Version);
        }

        var version = await context.AgentProposals
            .Where(p => p.ProposalId == upsert.ProposalId)
            .OrderByDescending(p => p.Version)
            .Select(p => (long?)p.Version)
            .FirstOrDefaultAsync(cancellationToken) ?? 0L;

        try
        {
            context.AgentProposals.Add(new AgentProposal
            {
                Id = Guid.NewGuid(),
                ProposalId = upsert.ProposalId,
                Version = version + 1,
                RunId = upsert.RunId,
                ArticleId = upsert.ArticleId,
                ArticleRevision = upsert.ArticleRevision,
                BaseContentHash = upsert.BaseContentHash,
                ContentHash = upsert.ContentHash,
                Summary = upsert.Summary,
                OwnerKey = upsert.OwnerKey,
                ExpiresAt = upsert.ExpiresAt,
                Status = AgentProposalStatus.Proposed,
            });
            await context.SaveChangesAsync(cancellationToken);
            return new ProposalUpsertResult(ProposalUpsertOutcome.Created, version + 1);
        }
        catch (DbUpdateException exception) when (IsUniqueViolation(exception))
        {
            // Yarış: aynı sürümü eşzamanlı bir teslim ekledi → no-op (idempotent).
            var raced = await FindRowAsync(upsert.ProposalId, upsert.ContentHash, cancellationToken)
                ?? throw new InvalidOperationException(
                    "proposal upsert unique çakışması sonrası kayıt bulunamadı", exception);
            return new ProposalUpsertResult(ProposalUpsertOutcome.AlreadyPresent, raced.Version);
        }
    }

    public async Task<CollaborationRunState?> GetRunStateAsync(Guid runId, CancellationToken cancellationToken = default)
    {
        var run = await context.AgentRuns
            .AsNoTracking()
            .FirstOrDefaultAsync(r => r.Id == runId, cancellationToken);
        if (run is null)
        {
            return null;
        }

        return new CollaborationRunState(run.Id, run.ConversationId, run.OwnerKey, run.Status.IsTerminal());
    }

    public async Task<AgentProposalSnapshot?> GetCurrentProposalAsync(
        Guid runId, Guid proposalId, CancellationToken cancellationToken = default)
    {
        var row = await context.AgentProposals
            .AsNoTracking()
            .Where(p => p.RunId == runId && p.ProposalId == proposalId)
            .OrderByDescending(p => p.Version)
            .FirstOrDefaultAsync(cancellationToken);
        return row is null ? null : ToSnapshot(row);
    }

    public async Task<ConfirmationTransition> ConfirmAsync(
        Guid proposalRowId, string contentHash, DateTimeOffset confirmedAt, CancellationToken cancellationToken = default)
    {
        // Koşullu geçiş: yalnız 'proposed' satır onaylanır; yarışta TEK çağrı kazanır.
        var affected = await context.AgentProposals
            .Where(p => p.Id == proposalRowId && p.Status == AgentProposalStatus.Proposed)
            .ExecuteUpdateAsync(setters => setters
                .SetProperty(p => p.Status, AgentProposalStatus.Confirmed)
                .SetProperty(p => p.ConfirmedAt, confirmedAt)
                .SetProperty(p => p.ConfirmedContentHash, contentHash)
                .SetProperty(p => p.UpdatedAt, DateTime.UtcNow), cancellationToken);
        if (affected == 1)
        {
            return ConfirmationTransition.Confirmed;
        }

        // Satır etkilenmedi: zaten geçmiş durumda. Aynı sürüm → Duplicate;
        // farklı sürüm onaylanmak istendi → VersionConflict.
        var row = await context.AgentProposals
            .AsNoTracking()
            .FirstOrDefaultAsync(p => p.Id == proposalRowId, cancellationToken);
        if (row is null)
        {
            throw new InvalidOperationException($"onaylanacak proposal satırı yok: {proposalRowId}");
        }

        if (row.Status != AgentProposalStatus.Proposed
            && string.Equals(row.ContentHash, contentHash, StringComparison.Ordinal))
        {
            return ConfirmationTransition.Duplicate;
        }

        return ConfirmationTransition.VersionConflict;
    }

    public async Task<bool> MarkResumeSentAsync(Guid proposalRowId, CancellationToken cancellationToken = default)
    {
        var affected = await context.AgentProposals
            .Where(p => p.Id == proposalRowId && p.Status == AgentProposalStatus.Confirmed)
            .ExecuteUpdateAsync(setters => setters
                .SetProperty(p => p.Status, AgentProposalStatus.ResumeSent)
                .SetProperty(p => p.UpdatedAt, DateTime.UtcNow), cancellationToken);
        return affected == 1;
    }

    // ------------------------------------------------------------ yardımcılar

    private async Task<AgentProposal?> FindRowAsync(Guid proposalId, string contentHash, CancellationToken ct) =>
        await context.AgentProposals
            .AsNoTracking()
            .FirstOrDefaultAsync(
                p => p.ProposalId == proposalId && p.ContentHash == contentHash, ct);

    private static AgentProposalSnapshot ToSnapshot(AgentProposal row) => new(
        row.Id, row.ProposalId, row.Version, row.RunId, row.ArticleId, row.ArticleRevision,
        row.BaseContentHash, row.ContentHash, row.Summary, row.OwnerKey,
        row.ExpiresAt, row.Status, row.ConfirmedAt, row.ConfirmedContentHash);

    private static bool IsUniqueViolation(DbUpdateException exception) =>
        exception.InnerException is PostgresException postgres
        && postgres.SqlState == UniqueViolationSqlState;
}
