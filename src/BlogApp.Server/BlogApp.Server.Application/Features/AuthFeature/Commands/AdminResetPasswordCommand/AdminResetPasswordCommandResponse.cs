using BlogApp.Server.Application.Common.Models;

namespace BlogApp.Server.Application.Features.AuthFeature.Commands.AdminResetPasswordCommand;

public class AdminResetPasswordCommandResponse
{
    public Result Result { get; init; } = default!;
}
