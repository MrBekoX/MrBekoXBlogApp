using BlogApp.Server.Domain.Common;
using BlogApp.Server.Domain.Enums;

namespace BlogApp.Server.Domain.Entities;

/// <summary>
/// Kullanıcı entity'si
/// </summary>
public class User : BaseAuditableEntity
{
    public string UserName { get; set; } = default!;
    public string Email { get; set; } = default!;
    public string PasswordHash { get; set; } = default!;
    public string? FirstName { get; set; }
    public string? LastName { get; set; }
    public string? Bio { get; set; }
    public string? AvatarUrl { get; set; }
    public UserRole Role { get; set; } = UserRole.Reader;
    public bool IsActive { get; set; } = true;
    public DateTime? LastLoginAt { get; set; }
    
    // Security - Account Lockout
    public int FailedLoginAttempts { get; set; } = 0;
    public DateTime? LockoutEndTime { get; set; }

    // Navigation properties
    public virtual ICollection<BlogPost> Posts { get; set; } = new List<BlogPost>();
    public virtual ICollection<Comment> Comments { get; set; } = new List<Comment>();
    public virtual ICollection<RefreshToken> RefreshTokens { get; set; } = new List<RefreshToken>();

    public string FullName => $"{FirstName} {LastName}".Trim();
}
