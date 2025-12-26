using BlogApp.Server.Domain.Common;

namespace BlogApp.Server.Domain.Entities;

/// <summary>
/// Yorum entity'si
/// </summary>
public class Comment : BaseAuditableEntity
{
    public string Content { get; set; } = default!;
    public bool IsApproved { get; set; }
    public string? GuestName { get; set; }
    public string? GuestEmail { get; set; }

    // Foreign keys
    public Guid PostId { get; set; }
    public Guid? UserId { get; set; }
    public Guid? ParentCommentId { get; set; }

    // Navigation properties
    public virtual BlogPost Post { get; set; } = default!;
    public virtual User? User { get; set; }
    public virtual Comment? ParentComment { get; set; }
    public virtual ICollection<Comment> Replies { get; set; } = new List<Comment>();

    public string AuthorName => User?.FullName ?? GuestName ?? "Anonymous";
}
