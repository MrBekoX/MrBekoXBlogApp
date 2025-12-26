using BlogApp.Server.Domain.Enums;

namespace BlogApp.Server.Application.DTOs.Posts;

/// <summary>
/// Post listesi için DTO
/// </summary>
public record PostDto
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

    // Related data
    public AuthorDto Author { get; init; } = default!;
    public CategoryDto? Category { get; init; }
    public List<TagDto> Tags { get; init; } = new();
}

/// <summary>
/// Post detay için DTO
/// </summary>
public record PostDetailDto : PostDto
{
    public string Content { get; init; } = default!;
    public string? MetaTitle { get; init; }
    public string? MetaDescription { get; init; }
    public string? MetaKeywords { get; init; }
    public int CommentCount { get; init; }
}

/// <summary>
/// Yazar bilgisi için DTO
/// </summary>
public record AuthorDto
{
    public Guid Id { get; init; }
    public string UserName { get; init; } = default!;
    public string? FullName { get; init; }
    public string? AvatarUrl { get; init; }
    public string? Bio { get; init; }
}

/// <summary>
/// Kategori için basit DTO
/// </summary>
public record CategoryDto
{
    public Guid Id { get; init; }
    public string Name { get; init; } = default!;
    public string Slug { get; init; } = default!;
}

/// <summary>
/// Tag için basit DTO
/// </summary>
public record TagDto
{
    public Guid Id { get; init; }
    public string Name { get; init; } = default!;
    public string Slug { get; init; } = default!;
}
