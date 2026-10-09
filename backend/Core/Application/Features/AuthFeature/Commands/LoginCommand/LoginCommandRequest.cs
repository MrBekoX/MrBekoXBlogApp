using BlogApp.Core.Application.Common.Models;
using BlogApp.Core.Application.Features.AuthFeature.DTOs;
using MediatR;

namespace BlogApp.Core.Application.Features.AuthFeature.Commands.LoginCommand;

public class LoginCommandRequest : IRequest<Result<AuthResponseDto>>
{
    public LoginCommandDto? LoginCommandRequestDto { get; set; }
}

