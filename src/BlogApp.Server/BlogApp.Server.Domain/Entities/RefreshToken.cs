using BlogApp.Server.Domain.Common;

namespace BlogApp.Server.Domain.Entities;

/// <summary>
/// Refresh token entity'si
/// </summary>
public class RefreshToken : BaseEntity
{
    public string Token { get; set; } = default!;
    public DateTime ExpiresAt { get; set; }
    public DateTime CreatedAt { get; set; }
    public string? CreatedByIp { get; set; }
    public DateTime? RevokedAt { get; set; }
    public string? RevokedByIp { get; set; }
    public string? ReplacedByToken { get; set; }
    public string? ReasonRevoked { get; set; }

    // Foreign key
    public Guid UserId { get; set; }

    // Navigation property
    public virtual User User { get; set; } = default!;

    public bool IsExpired => DateTime.UtcNow >= ExpiresAt;
    public bool IsRevoked => RevokedAt != null;
    public bool IsActive => !IsRevoked && !IsExpired;
}
