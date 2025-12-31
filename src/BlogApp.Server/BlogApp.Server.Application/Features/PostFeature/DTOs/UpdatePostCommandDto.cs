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
}

