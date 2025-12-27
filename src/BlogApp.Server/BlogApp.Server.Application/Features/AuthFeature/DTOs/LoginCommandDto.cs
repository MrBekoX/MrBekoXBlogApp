namespace BlogApp.Server.Application.Features.AuthFeature.DTOs;

public record LoginCommandDto
{
    public string Email { get; init; } = default!;
    public string Password { get; init; } = default!;
    public string? IpAddress { get; init; }
}
