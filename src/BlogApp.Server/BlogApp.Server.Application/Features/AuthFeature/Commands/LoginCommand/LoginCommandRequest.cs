using BlogApp.Server.Application.Features.AuthFeature.DTOs;
using MediatR;

namespace BlogApp.Server.Application.Features.AuthFeature.Commands.LoginCommand;

public class LoginCommandRequest : IRequest<LoginCommandResponse>
{
    public LoginCommandDto? LoginCommandRequestDto { get; set; }
}
