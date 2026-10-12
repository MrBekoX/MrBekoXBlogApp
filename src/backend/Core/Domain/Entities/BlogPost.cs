using BlogApp.Core.Domain.Common;
using BlogApp.Core.Domain.Enums;

namespace BlogApp.Core.Domain.Entities;

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

    /// <summary>
    /// Backend'in atadığı, makale başına monoton içerik revizyonu (D008). Yalnız makale
    /// İÇERİĞİ veya yayın GÖRÜNÜRLÜĞÜ değiştiğinde artar (yayınla/güncelle/yayından
    /// kaldır/sil); görüntülenme sayısı gibi ilgisiz güncellemeler bu değeri değiştirmez
    /// (plan B8). <see cref="Version"/> (xmin rowversion) bir MVCC concurrency token'ıdır
    /// ve revizyon anlamı TAŞIMAZ (L004) — ArticleContentChangedV1.article_revision bu
    /// alandan beslenir. 0 = henüz yayımlanmış içerik anı kaydedilmemiş.
    /// </summary>
    public long ContentRevision { get; set; }

    public string? MetaTitle { get; set; }
    public string? MetaDescription { get; set; }
    public string? MetaKeywords { get; set; }
    public int ReadingTimeMinutes { get; set; }

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
