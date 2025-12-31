namespace BlogApp.Server.Application.Features.CategoryFeature.DTOs;

public class GetAllCategoryQueryDto
{
    public Guid Id { get; set; }
    public string Name { get; set; } = null!;
    public string Slug { get; set; } = null!;
    public string? Description { get; set; }
    public string? ImageUrl { get; set; }
    public int DisplayOrder { get; set; }
    public bool IsActive { get; set; }
    public int PostCount { get; set; }
    public DateTime CreatedAt { get; set; }
}

