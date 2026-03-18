using BlogApp.Server.Domain.Entities;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;

namespace BlogApp.Server.Infrastructure.Persistence.Configurations;

public class IdempotencyRecordConfiguration : IEntityTypeConfiguration<IdempotencyRecord>
{
    public void Configure(EntityTypeBuilder<IdempotencyRecord> builder)
    {
        builder.ToTable("idempotency_records");

        builder.HasKey(x => x.Id);

        builder.Property(x => x.EndpointName)
            .IsRequired()
            .HasMaxLength(200);

        builder.Property(x => x.OperationId)
            .IsRequired()
            .HasMaxLength(128);

        builder.Property(x => x.RequestHash)
            .IsRequired()
            .HasMaxLength(128);

        builder.Property(x => x.CorrelationId)
            .IsRequired()
            .HasMaxLength(128);

        builder.Property(x => x.CausationId)
            .HasMaxLength(128);

        builder.Property(x => x.Status)
            .HasConversion<string>()
            .HasMaxLength(32);

        builder.Property(x => x.AcceptedResponseJson)
            .HasColumnType("jsonb");

        builder.Property(x => x.FinalResponseJson)
            .HasColumnType("jsonb");

        builder.Property(x => x.FinalResponseHeadersJson)
            .HasColumnType("jsonb");

        builder.Property(x => x.SessionId)
            .HasMaxLength(128);

        builder.Property(x => x.ResourceId)
            .HasMaxLength(128);

        builder.Property(x => x.ErrorCode)
            .HasMaxLength(64);

        builder.Property(x => x.ErrorMessage)
            .HasMaxLength(4000);

        builder.HasIndex(x => new { x.EndpointName, x.OperationId })
            .IsUnique()
            .HasDatabaseName("IX_idempotency_records_endpoint_operation")
            .HasFilter("\"IsDeleted\" = false");

        builder.HasIndex(x => x.CorrelationId)
            .HasDatabaseName("IX_idempotency_records_correlation")
            .HasFilter("\"IsDeleted\" = false");

        builder.HasIndex(x => new { x.Status, x.CreatedAt })
            .HasDatabaseName("IX_idempotency_records_status_createdat");
    }
}
