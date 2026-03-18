using BlogApp.Server.Domain.Entities;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;

namespace BlogApp.Server.Infrastructure.Persistence.Configurations;

public class OutboxMessageConfiguration : IEntityTypeConfiguration<OutboxMessage>
{
    public void Configure(EntityTypeBuilder<OutboxMessage> builder)
    {
        builder.ToTable("outbox_messages");

        builder.HasKey(x => x.Id);

        builder.Property(x => x.MessageId)
            .IsRequired();

        builder.Property(x => x.OperationId)
            .IsRequired()
            .HasMaxLength(128);

        builder.Property(x => x.CorrelationId)
            .HasMaxLength(128);

        builder.Property(x => x.CausationId)
            .HasMaxLength(128);

        builder.Property(x => x.RoutingKey)
            .IsRequired()
            .HasMaxLength(128);

        builder.Property(x => x.EventType)
            .IsRequired()
            .HasMaxLength(128);

        builder.Property(x => x.PayloadJson)
            .IsRequired()
            .HasColumnType("jsonb");

        builder.Property(x => x.HeadersJson)
            .HasColumnType("jsonb");

        builder.Property(x => x.Status)
            .HasConversion<string>()
            .HasMaxLength(32);

        builder.Property(x => x.LastError)
            .HasMaxLength(4000);

        builder.HasIndex(x => x.MessageId)
            .IsUnique()
            .HasDatabaseName("IX_outbox_messages_messageid")
            .HasFilter("\"IsDeleted\" = false");

        builder.HasIndex(x => new { x.Status, x.NextAttemptAt })
            .HasDatabaseName("IX_outbox_messages_status_nextattempt");
    }
}
