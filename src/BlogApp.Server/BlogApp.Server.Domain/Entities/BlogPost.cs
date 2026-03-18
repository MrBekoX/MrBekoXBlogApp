using BlogApp.Server.Domain.Common;
using BlogApp.Server.Domain.Enums;

namespace BlogApp.Server.Domain.Entities;

/// <summary>
/// Blog yazısı entity'si
/// </summary>
public class BlogPost : BaseAuditableEntity
{
    public string Title { get; set; } = default!;
    public string Slug { get; set; } = default!;
    public string Content { get; set; } = default!;
    public string? Excerpt { get; set; }
    public string? FeaturedImageUrl { get; set; }
    public PostStatus Status { get; set; } = PostStatus.Draft;
    public DateTime? PublishedAt { get; set; }
    public int ViewCount { get; set; }
    public int LikeCount { get; set; }
    public bool IsFeatured { get; set; }
    public uint Version { get; private set; }
    public string? MetaTitle { get; set; }
    public string? MetaDescription { get; set; }
    public string? MetaKeywords { get; set; }
    public int ReadingTimeMinutes { get; set; }

    // AI-Generated Fields
    /// <summary>
    /// AI tarafından oluşturulan makale özeti (RAG-based)
    /// </summary>
    public string? AiSummary { get; set; }

    /// <summary>
    /// AI tarafından çıkarılan anahtar kelimeler (virgülle ayrılmış)
    /// </summary>
    public string? AiKeywords { get; set; }

    /// <summary>
    /// AI tarafından hesaplanan tahmini okuma süresi (dakika)
    /// </summary>
    public int? AiEstimatedReadingTime { get; set; }

    /// <summary>
    /// AI tarafından oluşturulan SEO meta description
    /// </summary>
    public string? AiSeoDescription { get; set; }

    /// <summary>
    /// AI işlemesinin tamamlandığı tarih
    /// </summary>
    public DateTime? AiProcessedAt { get; set; }

    /// <summary>
    /// AI tarafından oluşturulan GEO optimizasyon verileri (JSON serialized)
    /// İçerir: optimized_title, geo_keywords, cultural_adaptations, vs.
    /// </summary>
    public string? AiGeoOptimization { get; set; }

    // Foreign keys
    public Guid AuthorId { get; set; }
    public Guid? CategoryId { get; set; }

    // Navigation properties
    public virtual User Author { get; set; } = default!;
    public virtual Category? Category { get; set; }
    public virtual ICollection<Tag> Tags { get; set; } = new List<Tag>();
    public virtual ICollection<Comment> Comments { get; set; } = new List<Comment>();

    /// <summary>
    /// Excerpt yoksa content'ten otomatik oluşturur
    /// </summary>
    public string GetExcerpt(int maxLength = 200)
    {
        if (!string.IsNullOrEmpty(Excerpt))
            return Excerpt;

        if (string.IsNullOrEmpty(Content))
            return string.Empty;

        var plainText = Content.Length > maxLength
            ? Content[..maxLength] + "..."
            : Content;

        return plainText;
    }

    /// <summary>
    /// Tahmini okuma süresini hesaplar
    /// </summary>
    public void CalculateReadingTime(int wordsPerMinute = 200)
    {
        if (string.IsNullOrEmpty(Content))
        {
            ReadingTimeMinutes = 0;
            return;
        }

        var wordCount = Content.Split(' ', StringSplitOptions.RemoveEmptyEntries).Length;
        ReadingTimeMinutes = Math.Max(1, (int)Math.Ceiling((double)wordCount / wordsPerMinute));
    }

    /// <summary>
    /// Yazıyı yayınlar
    /// </summary>
    public void Publish()
    {
        Status = PostStatus.Published;
        PublishedAt = DateTime.UtcNow;
    }

    /// <summary>
    /// Yazıyı arşivler
    /// </summary>
    public void Archive()
    {
        Status = PostStatus.Archived;
    }

    /// <summary>
    /// Yazıyı taslağa çevirir
    /// </summary>
    public void Unpublish()
    {
        Status = PostStatus.Draft;
        PublishedAt = null;
    }
}
