using BlogApp.Server.Domain.Entities;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;

namespace BlogApp.Server.Infrastructure.Persistence.Configurations;

/// <summary>
/// RefreshToken entity configuration
/// </summary>
public class RefreshTokenConfiguration : IEntityTypeConfiguration<RefreshToken>
{
    public void Configure(EntityTypeBuilder<RefreshToken> builder)
    {
        builder.ToTable("refresh_tokens");

        builder.HasKey(r => r.Id);

        builder.Property(r => r.Token)
            .IsRequired()
            .HasMaxLength(500);

        builder.Property(r => r.CreatedByIp)
            .HasMaxLength(50);

        builder.Property(r => r.RevokedByIp)
            .HasMaxLength(50);

        builder.Property(r => r.ReplacedByToken)
            .HasMaxLength(500);

        builder.Property(r => r.ReasonRevoked)
            .HasMaxLength(200);

        // Indexes
        builder.HasIndex(r => r.Token)
            .IsUnique();  // Token must be unique
        builder.HasIndex(r => r.ExpiresAt);
        builder.HasIndex(r => r.UserId);  // For querying user's tokens

        // Relationships
        builder.HasOne(r => r.User)
            .WithMany(u => u.RefreshTokens)
            .HasForeignKey(r => r.UserId)
            .OnDelete(DeleteBehavior.Cascade);
    }
}
