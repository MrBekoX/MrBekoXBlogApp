using BlogApp.Server.Application.Common.Interfaces;
using BlogApp.Server.Application.Features.AuthFeature.DTOs;
using MediatR;

namespace BlogApp.Server.Application.Features.AuthFeature.Commands.RegisterCommand;

public class RegisterCommandRequest : IRequest<RegisterCommandResponse>, IIdempotentCommand
{
    public RegisterCommandDto? RegisterCommandRequestDto { get; set; }

    public string OperationId { get; set; } = string.Empty;
    public string IdempotencyEndpointName => "auth.register";
}

