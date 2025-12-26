namespace BlogApp.Server.Application.DTOs.Tags;

/// <summary>
/// Tag detay DTO
/// </summary>
public record TagDetailDto
{
    public Guid Id { get; init; }
    public string Name { get; init; } = default!;
    public string Slug { get; init; } = default!;
    public int PostCount { get; init; }
    public DateTime CreatedAt { get; init; }
}
