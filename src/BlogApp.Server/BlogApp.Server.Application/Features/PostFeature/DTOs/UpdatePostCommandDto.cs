namespace BlogApp.Server.Application.Features.PostFeature.DTOs;

public record UpdatePostCommandDto
{
    public Guid Id { get; set; }
    public string Title { get; init; } = default!;
    public string Content { get; init; } = default!;
    public string? Excerpt { get; init; }
    public string? FeaturedImageUrl { get; init; }
    public List<Guid> CategoryIds { get; init; } = new();
    public List<string> TagNames { get; init; } = new();
    public string? MetaTitle { get; init; }
    public string? MetaDescription { get; init; }
    public string? MetaKeywords { get; init; }
    public bool IsFeatured { get; init; }
    public string Status { get; init; } = "Draft";

    // AI-Generated Fields
    /// <summary>
    /// AI tarafından oluşturulan makale özeti
    /// </summary>
    public string? AiSummary { get; init; }

    /// <summary>
    /// AI tarafından çıkarılan anahtar kelimeler
    /// </summary>
    public string? AiKeywords { get; init; }

    /// <summary>
    /// AI tarafından hesaplanan tahmini okuma süresi
    /// </summary>
    public int? AiEstimatedReadingTime { get; init; }

    /// <summary>
    /// AI tarafından oluşturulan SEO meta description
    /// </summary>
    public string? AiSeoDescription { get; init; }

    /// <summary>
    /// AI tarafından oluşturulan GEO optimizasyon verileri
    /// </summary>
    public string? AiGeoOptimization { get; init; }
}

