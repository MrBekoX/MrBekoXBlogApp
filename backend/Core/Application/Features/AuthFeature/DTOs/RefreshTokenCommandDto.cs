namespace BlogApp.Core.Application.Features.AuthFeature.DTOs;

public record RefreshTokenCommandDto
{
    public string RefreshToken { get; init; } = default!;
    public string? IpAddress { get; init; }
}

