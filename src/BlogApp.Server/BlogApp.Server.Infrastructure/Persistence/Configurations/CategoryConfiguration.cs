using BlogApp.Server.Domain.Entities;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;

namespace BlogApp.Server.Infrastructure.Persistence.Configurations;

/// <summary>
/// Category entity configuration
/// </summary>
public class CategoryConfiguration : IEntityTypeConfiguration<Category>
{
    public void Configure(EntityTypeBuilder<Category> builder)
    {
        builder.ToTable("categories");

        builder.HasKey(c => c.Id);

        builder.Property(c => c.Name)
            .IsRequired()
            .HasMaxLength(100);

        builder.Property(c => c.Slug)
            .IsRequired()
            .HasMaxLength(120);

        builder.Property(c => c.Description)
            .HasMaxLength(500);

        builder.Property(c => c.ImageUrl)
            .HasMaxLength(500);

        // Indexes - Partial unique index (only for non-deleted records)
        builder.HasIndex(c => c.Slug)
            .IsUnique()
            .HasFilter("\"IsDeleted\" = false");

        builder.HasIndex(c => c.DisplayOrder);
        builder.HasIndex(c => c.IsActive);
    }
}
