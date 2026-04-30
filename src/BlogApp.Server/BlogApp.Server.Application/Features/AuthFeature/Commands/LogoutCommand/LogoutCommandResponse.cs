using BlogApp.Server.Application.Common.Models;

namespace BlogApp.Server.Application.Features.AuthFeature.Commands.LogoutCommand;

public class LogoutCommandResponse
{
    public Result Result { get; set; } = null!;
}
