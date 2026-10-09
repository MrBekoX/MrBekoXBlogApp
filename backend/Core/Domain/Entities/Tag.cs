using BlogApp.Core.Domain.Common;

namespace BlogApp.Core.Domain.Entities;

/// <summary>
/// Tag entity'si
/// </summary>
public class Tag : BaseAuditableEntity
{
    public string Name { get; set; } = default!;
    public string Slug { get; set; } = default!;

    // Navigation properties
    public virtual ICollection<BlogPost> Posts { get; set; } = new List<BlogPost>();
}
