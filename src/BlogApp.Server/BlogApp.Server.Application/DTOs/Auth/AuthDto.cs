namespace BlogApp.Server.Application.DTOs.Auth;

/// <summary>
/// Login response DTO
/// </summary>
public record AuthResponseDto
{
    public string AccessToken { get; init; } = default!;
    public string RefreshToken { get; init; } = default!;
    public DateTime ExpiresAt { get; init; }
    public UserInfoDto User { get; init; } = default!;
}

/// <summary>
/// Auth response without tokens (tokens are in HttpOnly cookies)
/// </summary>
public record AuthResponseWithCookiesDto
{
    public DateTime ExpiresAt { get; init; }
    public UserInfoDto User { get; init; } = default!;
}

/// <summary>
/// Kullanıcı bilgi DTO (auth için)
/// </summary>
public record UserInfoDto
{
    public Guid Id { get; init; }
    public string UserName { get; init; } = default!;
    public string Email { get; init; } = default!;
    public string? FullName { get; init; }
    public string? AvatarUrl { get; init; }
    public string Role { get; init; } = default!;
}
