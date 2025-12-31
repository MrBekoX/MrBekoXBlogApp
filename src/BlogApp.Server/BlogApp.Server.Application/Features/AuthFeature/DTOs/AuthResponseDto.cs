namespace BlogApp.Server.Application.Features.AuthFeature.DTOs;

public record AuthResponseDto
{
    public string AccessToken { get; init; } = default!;
    public string RefreshToken { get; init; } = default!;
    public DateTime ExpiresAt { get; init; }
    public UserInfoDto User { get; init; } = default!;
}

public record AuthResponseWithCookiesDto
{
    public DateTime ExpiresAt { get; init; }
    public UserInfoDto User { get; init; } = default!;
}

public record UserInfoDto
{
    public Guid Id { get; init; }
    public string UserName { get; init; } = default!;
    public string Email { get; init; } = default!;
    public string? FullName { get; init; }
    public string? AvatarUrl { get; init; }
    public string Role { get; init; } = default!;
}

