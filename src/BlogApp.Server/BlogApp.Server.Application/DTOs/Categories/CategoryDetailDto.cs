namespace BlogApp.Server.Application.DTOs.Categories;

/// <summary>
/// Kategori detay DTO
/// </summary>
public record CategoryDetailDto
{
    public Guid Id { get; init; }
    public string Name { get; init; } = default!;
    public string Slug { get; init; } = default!;
    public string? Description { get; init; }
    public string? ImageUrl { get; init; }
    public int DisplayOrder { get; init; }
    public bool IsActive { get; init; }
    public int PostCount { get; init; }
    public DateTime CreatedAt { get; init; }
}
