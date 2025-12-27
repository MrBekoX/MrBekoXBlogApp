using BlogApp.Server.Application.Features.AuthFeature.DTOs;
using MediatR;

namespace BlogApp.Server.Application.Features.AuthFeature.Commands.RegisterCommand;

public class RegisterCommandRequest : IRequest<RegisterCommandResponse>
{
    public RegisterCommandDto? RegisterCommandRequestDto { get; set; }
}
