namespace BlogApp.Server.Application.Features.CategoryFeature.DTOs;

public class UpdateCategoryCommandDto
{
    public Guid Id { get; set; }
    public string Name { get; set; } = null!;
    public string? Description { get; set; }
    public string? ImageUrl { get; set; }
    public int DisplayOrder { get; set; }
}
