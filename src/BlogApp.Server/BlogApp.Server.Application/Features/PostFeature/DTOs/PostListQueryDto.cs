using BlogApp.Server.Domain.Enums;

namespace BlogApp.Server.Application.Features.PostFeature.DTOs;

public record PostListQueryDto
{
    public Guid Id { get; init; }
    public string Title { get; init; } = default!;
    public string Slug { get; init; } = default!;
    public string? Excerpt { get; init; }
    public string? FeaturedImageUrl { get; init; }
    public PostStatus Status { get; init; }
    public DateTime? PublishedAt { get; init; }
    public int ViewCount { get; init; }
    public int LikeCount { get; init; }
    public bool IsFeatured { get; init; }
    public int ReadingTimeMinutes { get; init; }
    public DateTime CreatedAt { get; init; }
    public PostAuthorDto Author { get; init; } = default!;
    public PostCategoryDto? Category { get; init; }
    public List<PostTagDto> Tags { get; init; } = new();
}

public record PostAuthorDto
{
    public Guid Id { get; init; }
    public string UserName { get; init; } = default!;
    public string? FullName { get; init; }
    public string? AvatarUrl { get; init; }
    public string? Bio { get; init; }
}

public record PostCategoryDto
{
    public Guid Id { get; init; }
    public string Name { get; init; } = default!;
    public string Slug { get; init; } = default!;
}

public record PostTagDto
{
    public Guid Id { get; init; }
    public string Name { get; init; } = default!;
    public string Slug { get; init; } = default!;
}
