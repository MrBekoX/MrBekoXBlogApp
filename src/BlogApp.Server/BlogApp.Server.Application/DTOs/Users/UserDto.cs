using BlogApp.Server.Domain.Enums;

namespace BlogApp.Server.Application.DTOs.Users;

/// <summary>
/// Kullanıcı DTO
/// </summary>
public record UserDto
{
    public Guid Id { get; init; }
    public string UserName { get; init; } = default!;
    public string Email { get; init; } = default!;
    public string? FirstName { get; init; }
    public string? LastName { get; init; }
    public string? FullName { get; init; }
    public string? Bio { get; init; }
    public string? AvatarUrl { get; init; }
    public UserRole Role { get; init; }
    public bool IsActive { get; init; }
    public DateTime? LastLoginAt { get; init; }
    public DateTime CreatedAt { get; init; }
}
