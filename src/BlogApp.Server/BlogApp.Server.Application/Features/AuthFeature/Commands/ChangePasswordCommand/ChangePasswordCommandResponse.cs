using BlogApp.Server.Application.Common.Models;

namespace BlogApp.Server.Application.Features.AuthFeature.Commands.ChangePasswordCommand;

public class ChangePasswordCommandResponse
{
    public Result Result { get; init; } = default!;
}
