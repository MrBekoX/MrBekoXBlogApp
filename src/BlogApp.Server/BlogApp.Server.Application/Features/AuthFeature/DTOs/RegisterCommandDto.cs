namespace BlogApp.Server.Application.Features.AuthFeature.DTOs;

public record RegisterCommandDto
{
    public string UserName { get; init; } = default!;
    public string Email { get; init; } = default!;
    public string Password { get; init; } = default!;
    public string ConfirmPassword { get; init; } = default!;
    public string? FirstName { get; init; }
    public string? LastName { get; init; }
    public string? IpAddress { get; init; }
}
