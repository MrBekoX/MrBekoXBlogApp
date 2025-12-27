using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.Features.AuthFeature.DTOs;

namespace BlogApp.Server.Application.Features.AuthFeature.Commands.RefreshTokenCommand;

public class RefreshTokenCommandResponse
{
    public Result<AuthResponseDto> Result { get; set; } = null!;
}
