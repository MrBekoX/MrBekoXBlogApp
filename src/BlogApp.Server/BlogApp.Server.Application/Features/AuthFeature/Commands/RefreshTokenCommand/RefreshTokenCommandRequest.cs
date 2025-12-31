using BlogApp.Server.Application.Features.AuthFeature.DTOs;
using MediatR;

namespace BlogApp.Server.Application.Features.AuthFeature.Commands.RefreshTokenCommand;

public class RefreshTokenCommandRequest : IRequest<RefreshTokenCommandResponse>
{
    public RefreshTokenCommandDto? RefreshTokenCommandRequestDto { get; set; }
}

