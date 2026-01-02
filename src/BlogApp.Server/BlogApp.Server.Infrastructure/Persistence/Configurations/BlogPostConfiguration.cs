using BlogApp.Server.Domain.Entities;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;

namespace BlogApp.Server.Infrastructure.Persistence.Configurations;

/// <summary>
/// BlogPost entity configuration
/// </summary>
public class BlogPostConfiguration : IEntityTypeConfiguration<BlogPost>
{
    public void Configure(EntityTypeBuilder<BlogPost> builder)
    {
        builder.ToTable("posts");

        builder.HasKey(p => p.Id);

        builder.Property(p => p.Title)
            .IsRequired()
            .HasMaxLength(200);

        builder.Property(p => p.Slug)
            .IsRequired()
            .HasMaxLength(250);

        builder.Property(p => p.Content)
            .IsRequired();

        builder.Property(p => p.Excerpt)
            .HasMaxLength(500);

        builder.Property(p => p.FeaturedImageUrl)
            .HasMaxLength(500);

        builder.Property(p => p.MetaTitle)
            .HasMaxLength(70);

        builder.Property(p => p.MetaDescription)
            .HasMaxLength(160);

        builder.Property(p => p.MetaKeywords)
            .HasMaxLength(200);

        // Indexes
        builder.HasIndex(p => p.Slug)
            .IsUnique();

        builder.HasIndex(p => p.Status);
        builder.HasIndex(p => p.PublishedAt);
        builder.HasIndex(p => p.CreatedAt);
        builder.HasIndex(p => p.IsFeatured);
        
        // Composite index for common query patterns (status + published date)
        builder.HasIndex(p => new { p.Status, p.PublishedAt })
            .HasDatabaseName("IX_posts_status_publishedat");
        
        // Composite index for featured posts query
        builder.HasIndex(p => new { p.Status, p.IsFeatured, p.PublishedAt })
            .HasDatabaseName("IX_posts_status_isfeatured_publishedat");
        
        // Soft delete filter index
        builder.HasIndex(p => new { p.IsDeleted, p.Status })
            .HasDatabaseName("IX_posts_isdeleted_status");
        
        // GIN index for full-text search on title (PostgreSQL specific)
        // Note: For production, consider adding a tsvector column with GIN index
        // ALTER TABLE posts ADD COLUMN search_vector tsvector;
        // CREATE INDEX IX_posts_search_vector ON posts USING GIN(search_vector);
        builder.HasIndex(p => p.Title)
            .HasDatabaseName("IX_posts_title");
        
        // Index for category filtering
        builder.HasIndex(p => new { p.CategoryId, p.Status })
            .HasDatabaseName("IX_posts_categoryid_status");

        // Relationships
        builder.HasOne(p => p.Author)
            .WithMany(u => u.Posts)
            .HasForeignKey(p => p.AuthorId)
            .OnDelete(DeleteBehavior.Restrict);

        builder.HasOne(p => p.Category)
            .WithMany(c => c.Posts)
            .HasForeignKey(p => p.CategoryId)
            .OnDelete(DeleteBehavior.SetNull);

        // Many-to-Many with Tags
        builder.HasMany(p => p.Tags)
            .WithMany(t => t.Posts)
            .UsingEntity<Dictionary<string, object>>(
                "post_tags",
                j => j.HasOne<Tag>().WithMany().HasForeignKey("tag_id"),
                j => j.HasOne<BlogPost>().WithMany().HasForeignKey("post_id"));
    }
}
