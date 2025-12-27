using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.Features.AuthFeature.DTOs;

namespace BlogApp.Server.Application.Features.AuthFeature.Commands.LoginCommand;

public class LoginCommandResponse
{
    public Result<AuthResponseDto> Result { get; set; } = null!;
}
