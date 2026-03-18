using BlogApp.Server.Domain.Entities;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;

namespace BlogApp.Server.Infrastructure.Persistence.Configurations;

public class ConsumerInboxMessageConfiguration : IEntityTypeConfiguration<ConsumerInboxMessage>
{
    public void Configure(EntityTypeBuilder<ConsumerInboxMessage> builder)
    {
        builder.ToTable("consumer_inbox_messages");

        builder.HasKey(x => x.Id);

        builder.Property(x => x.ConsumerName)
            .IsRequired()
            .HasMaxLength(200);

        builder.Property(x => x.OperationId)
            .IsRequired()
            .HasMaxLength(128);

        builder.Property(x => x.CorrelationId)
            .HasMaxLength(128);

        builder.Property(x => x.Status)
            .HasConversion<string>()
            .HasMaxLength(32);

        builder.Property(x => x.LastError)
            .HasMaxLength(4000);

        builder.HasIndex(x => new { x.ConsumerName, x.OperationId })
            .IsUnique()
            .HasDatabaseName("IX_consumer_inbox_consumer_operation")
            .HasFilter("\"IsDeleted\" = false");

        builder.HasIndex(x => new { x.ConsumerName, x.MessageId })
            .HasDatabaseName("IX_consumer_inbox_consumer_message");
    }
}
