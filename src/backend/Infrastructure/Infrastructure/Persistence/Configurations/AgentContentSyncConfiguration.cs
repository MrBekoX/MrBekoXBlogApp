using BlogApp.Core.Domain.Entities;
using BlogApp.Core.Domain.Enums;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;

namespace BlogApp.Infrastructure.Persistence.Configurations;

/// <summary>
/// B8 ilk içerik senkronizasyonu kaydı (watermark) yapılandırması — ADDITIVE.
/// </summary>
public class AgentContentSyncConfiguration : IEntityTypeConfiguration<AgentContentSync>
{
    public void Configure(EntityTypeBuilder<AgentContentSync> builder)
    {
        builder.ToTable("agent_content_syncs");

        builder.HasKey(s => s.SyncId);

        builder.Property(s => s.SyncId)
            .HasColumnName("sync_id");

        builder.Property(s => s.Status)
            .HasColumnName("status")
            .IsRequired();

        builder.Property(s => s.BatchSize)
            .HasColumnName("batch_size");

        builder.Property(s => s.ItemCount)
            .HasColumnName("item_count");

        builder.Property(s => s.TotalBatches)
            .HasColumnName("total_batches");

        builder.Property(s => s.RevisionWatermark)
            .HasColumnName("revision_watermark");

        builder.Property(s => s.StartedAt)
            .HasColumnName("started_at");

        builder.Property(s => s.CompletedAt)
            .HasColumnName("completed_at");

        // Operasyonel sorgular: son senkronlar ve Running'de kalanlar.
        builder.HasIndex(s => s.Status)
            .HasDatabaseName("IX_agent_content_syncs_status");
        builder.HasIndex(s => s.StartedAt)
            .HasDatabaseName("IX_agent_content_syncs_started_at");
    }
}
