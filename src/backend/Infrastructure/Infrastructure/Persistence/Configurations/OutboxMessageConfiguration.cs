using BlogApp.Core.Domain.Entities;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;

namespace BlogApp.Infrastructure.Persistence.Configurations;

/// <summary>
/// Transactional outbox tablosu (B3). Relay claim sorgusu (FOR UPDATE SKIP LOCKED)
/// Status + ClaimLeaseUntil üzerinden çalışır; MessageId unique'dir çünkü kayıp confirm
/// aynı message_id ile tekrar yayınlanır (plan satır 301).
/// </summary>
public class OutboxMessageConfiguration : IEntityTypeConfiguration<OutboxMessage>
{
    public void Configure(EntityTypeBuilder<OutboxMessage> builder)
    {
        builder.ToTable("outbox_messages");

        builder.HasKey(x => x.Id);

        builder.Property(x => x.MessageId)
            .IsRequired()
            .HasMaxLength(64);

        builder.Property(x => x.MessageType)
            .IsRequired()
            .HasMaxLength(64);

        builder.Property(x => x.Exchange)
            .IsRequired()
            .HasMaxLength(128);

        builder.Property(x => x.RoutingKey)
            .IsRequired()
            .HasMaxLength(128);

        builder.Property(x => x.CorrelationId)
            .IsRequired()
            .HasMaxLength(64);

        // Byte-exact tekrar yayın için jsonb normalizasyonu yerine metin saklanır.
        builder.Property(x => x.EnvelopeJson)
            .IsRequired()
            .HasColumnType("text");

        builder.Property(x => x.Status)
            .IsRequired()
            .HasConversion<string>()
            .HasMaxLength(32);

        builder.Property(x => x.ClaimedBy)
            .HasMaxLength(128);

        builder.Property(x => x.LastError)
            .HasMaxLength(4000);

        builder.HasIndex(x => x.MessageId)
            .IsUnique()
            .HasDatabaseName("UX_outbox_messages_message_id");

        // Relay claim taraması: beklemede olanlar veya lease'i dolmuş claim'ler.
        builder.HasIndex(x => new { x.Status, x.ClaimLeaseUntil })
            .HasDatabaseName("IX_outbox_messages_status_lease");

        builder.HasIndex(x => x.RunId)
            .HasDatabaseName("IX_outbox_messages_run");
    }
}
