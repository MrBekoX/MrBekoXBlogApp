using BlogApp.Core.Domain.Entities;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;

namespace BlogApp.Infrastructure.Persistence.Configurations;

/// <summary>
/// AgentEventInbox tablo yapılandırması (B5). Additive tablo; PK (ConsumerName,
/// MessageId) consumer kapsamlı mesaj tekilliğini DB'de keser (tekrar teslimde
/// projection yeniden uygulanmaz).
/// </summary>
public class AgentEventInboxConfiguration : IEntityTypeConfiguration<AgentEventInbox>
{
    public void Configure(EntityTypeBuilder<AgentEventInbox> builder)
    {
        builder.ToTable("agent_event_inbox");

        builder.HasKey(i => new { i.ConsumerName, i.MessageId });

        builder.Property(i => i.ConsumerName)
            .IsRequired()
            .HasMaxLength(64);

        builder.Property(i => i.MessageType)
            .IsRequired()
            .HasMaxLength(64);

        builder.Property(i => i.Status)
            .IsRequired()
            .HasMaxLength(16);

        builder.Property(i => i.Detail)
            .HasMaxLength(512);

        // Agent live-steps replay türetme kaynağı (ADDITIVE): payload JSON'u text
        // olarak saklanır (bilinçli seçim: bozuk/eski satırlar da kalıcıdır ve replay
        // "alanlar null, olay düşmez" sözleşmesiyle karşılanır); boyut zarf üst
        // sınırıyla (256 KiB) sınırlıdır.
        builder.Property(i => i.PayloadJson);

        builder.Property(i => i.ProgressMessage)
            .HasMaxLength(2000); // payload sözleşmesi: message maxLength 2000

        builder.Property(i => i.CreatedAt).IsRequired();

        // Run bazlı denetim sorguları (operasyon/karantina incelemesi).
        builder.HasIndex(i => i.RunId)
            .HasDatabaseName("IX_agent_event_inbox_run");
        builder.HasIndex(i => i.Status)
            .HasDatabaseName("IX_agent_event_inbox_status");
    }
}
