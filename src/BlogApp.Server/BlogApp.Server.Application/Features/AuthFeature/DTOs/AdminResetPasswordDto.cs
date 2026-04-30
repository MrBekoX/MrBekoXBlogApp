namespace BlogApp.Server.Application.Features.AuthFeature.DTOs;

public record AdminResetPasswordDto
{
    public Guid UserId { get; init; }
    public string NewPassword { get; init; } = default!;
}
