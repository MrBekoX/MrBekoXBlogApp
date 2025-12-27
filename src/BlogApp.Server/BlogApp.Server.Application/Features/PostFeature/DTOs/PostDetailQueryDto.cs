using BlogApp.Server.Domain.Enums;

namespace BlogApp.Server.Application.Features.PostFeature.DTOs;

public record PostDetailQueryDto
{
    public Guid Id { get; init; }
    public string Title { get; init; } = default!;
    public string Slug { get; init; } = default!;
    public string Content { get; init; } = default!;
    public string? Excerpt { get; init; }
    public string? FeaturedImageUrl { get; init; }
    public PostStatus Status { get; init; }
    public DateTime? PublishedAt { get; init; }
    public int ViewCount { get; init; }
    public int LikeCount { get; init; }
    public bool IsFeatured { get; init; }
    public int ReadingTimeMinutes { get; init; }
    public string? MetaTitle { get; init; }
    public string? MetaDescription { get; init; }
    public string? MetaKeywords { get; init; }
    public int CommentCount { get; init; }
    public DateTime CreatedAt { get; init; }
    public PostAuthorDto Author { get; init; } = default!;
    public PostCategoryDto? Category { get; init; }
    public List<PostTagDto> Tags { get; init; } = new();
}
