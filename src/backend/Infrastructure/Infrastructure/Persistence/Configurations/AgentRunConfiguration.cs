using BlogApp.Core.Domain.Entities;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;

namespace BlogApp.Infrastructure.Persistence.Configurations;

/// <summary>
/// AgentRun tablo yapılandırması (B3). Migration sahipliği: Infrastructure (D011);
/// additive tablo, mevcut entity'lere dokunmaz. Kural: run.Id = sözleşme run_id.
/// </summary>
public class AgentRunConfiguration : IEntityTypeConfiguration<AgentRun>
{
    public void Configure(EntityTypeBuilder<AgentRun> builder)
    {
        builder.ToTable("agent_runs");

        builder.HasKey(x => x.Id);

        builder.Property(x => x.ConversationId).IsRequired();

        builder.Property(x => x.TurnSequence).IsRequired();

        builder.Property(x => x.OwnerKey)
            .IsRequired()
            .HasMaxLength(160);

        builder.Property(x => x.GuestSessionId)
            .HasMaxLength(128);

        builder.Property(x => x.IdempotencyKey)
            .IsRequired()
            .HasMaxLength(128);

        builder.Property(x => x.IdempotencyPayloadHash)
            .IsRequired()
            .HasMaxLength(64);

        builder.Property(x => x.Status)
            .IsRequired()
            .HasConversion<string>()
            .HasMaxLength(32);

        builder.Property(x => x.Question)
            .IsRequired()
            .HasMaxLength(8000);

        builder.Property(x => x.Language)
            .IsRequired()
            .HasMaxLength(16);

        builder.Property(x => x.ModePreference)
            .IsRequired()
            .HasMaxLength(32);

        builder.Property(x => x.BudgetProfile)
            .IsRequired()
            .HasMaxLength(128);

        builder.Property(x => x.ArticleContentHash)
            .HasMaxLength(64);

        builder.Property(x => x.ContextSnapshotReference)
            .IsRequired()
            .HasMaxLength(512);

        builder.Property(x => x.ContextSnapshotJson)
            .IsRequired()
            .HasColumnType("jsonb");

        builder.Property(x => x.DeadlineAt).IsRequired();
        builder.Property(x => x.AcceptedAt).IsRequired();

        // İstemcinin tekrarlı kabulü: sahip + anahtar benzersiz (Postgres NULL-distinct
        // sorununa karşı OwnerKey sentetik sütundur).
        builder.HasIndex(x => new { x.OwnerKey, x.IdempotencyKey })
            .IsUnique()
            .HasDatabaseName("UX_agent_runs_owner_idempotency");

        // turn_sequence konuşma içinde monoton; eşzamanlı kabul yarışını DB'de keser.
        builder.HasIndex(x => new { x.ConversationId, x.TurnSequence })
            .IsUnique()
            .HasDatabaseName("UX_agent_runs_conversation_turn");

        builder.HasIndex(x => new { x.OwnerKey, x.Status })
            .HasDatabaseName("IX_agent_runs_owner_status");

        builder.HasIndex(x => x.ArticleId)
            .HasDatabaseName("IX_agent_runs_article");
    }
}
