namespace BlogApp.Core.Application.Features.AuthFeature.DTOs;

public record ChangePasswordDto
{
    public string CurrentPassword { get; init; } = default!;
    public string NewPassword { get; init; } = default!;
    public string ConfirmNewPassword { get; init; } = default!;
}
