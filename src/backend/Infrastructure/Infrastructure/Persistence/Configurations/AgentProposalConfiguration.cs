using BlogApp.Core.Domain.Entities;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;

namespace BlogApp.Infrastructure.Persistence.Configurations;

/// <summary>
/// AgentProposal tablo yapılandırması (B9). Migration sahipliği: Infrastructure (D011);
/// ADDITIVE tablo — mevcut entity/config'lere dokunmaz. ``(ProposalId, ContentHash)``
/// benzersizliği projection tekrarını ve onay sürüm bağını DB'de keser; Status CHECK
/// kısıtı durum makinesi kümesini sabitler (proposed → confirmed → resume_sent).
/// </summary>
public class AgentProposalConfiguration : IEntityTypeConfiguration<AgentProposal>
{
    public void Configure(EntityTypeBuilder<AgentProposal> builder)
    {
        builder.ToTable("agent_proposals");

        builder.HasKey(x => x.Id);

        builder.Property(x => x.ProposalId).IsRequired();
        builder.Property(x => x.Version).IsRequired();
        builder.Property(x => x.RunId).IsRequired();
        builder.Property(x => x.ArticleId).IsRequired();
        builder.Property(x => x.ArticleRevision).IsRequired();

        builder.Property(x => x.BaseContentHash)
            .IsRequired()
            .HasMaxLength(64);

        builder.Property(x => x.ContentHash)
            .IsRequired()
            .HasMaxLength(64);

        builder.Property(x => x.Summary)
            .IsRequired()
            .HasMaxLength(8000);

        builder.Property(x => x.OwnerKey)
            .IsRequired()
            .HasMaxLength(160);

        builder.Property(x => x.ExpiresAt).IsRequired();

        builder.Property(x => x.Status)
            .IsRequired()
            .HasMaxLength(16)
            .HasConversion<string>();

        builder.Property(x => x.ConfirmedContentHash)
            .HasMaxLength(64);

        builder.ToTable(t => t.HasCheckConstraint(
            "CK_agent_proposals_status",
            "\"Status\" IN ('proposed', 'confirmed', 'resume_sent')"));

        // Sürüm tekilleştirme: aynı proposal'ın aynı içerik sürümü TEK satırdır
        // (idempotent upsert'in DB güvencesi; eşzamanlı tekrar unique ile kesilir).
        builder.HasIndex(x => new { x.ProposalId, x.ContentHash })
            .IsUnique()
            .HasDatabaseName("UX_agent_proposals_proposal_content");

        builder.HasIndex(x => new { x.ProposalId, x.Version })
            .IsUnique()
            .HasDatabaseName("UX_agent_proposals_proposal_version");

        builder.HasIndex(x => x.RunId)
            .HasDatabaseName("IX_agent_proposals_run");

        builder.HasIndex(x => new { x.OwnerKey, x.Status })
            .HasDatabaseName("IX_agent_proposals_owner_status");
    }
}
