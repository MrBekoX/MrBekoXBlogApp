using BlogApp.Server.Domain.Common;

namespace BlogApp.Server.Domain.Entities;

/// <summary>
/// Kategori entity'si
/// </summary>
public class Category : BaseAuditableEntity
{
    public string Name { get; set; } = default!;
    public string Slug { get; set; } = default!;
    public string? Description { get; set; }
    public string? ImageUrl { get; set; }
    public int DisplayOrder { get; set; }
    public bool IsActive { get; set; } = true;

    // Navigation properties
    public virtual ICollection<BlogPost> Posts { get; set; } = new List<BlogPost>();
}
