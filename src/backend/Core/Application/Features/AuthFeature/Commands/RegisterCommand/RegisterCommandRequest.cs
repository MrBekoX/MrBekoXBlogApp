using BlogApp.Core.Application.Common.Interfaces;
using BlogApp.Core.Application.Common.Models;
using BlogApp.Core.Application.Features.AuthFeature.DTOs;
using MediatR;

namespace BlogApp.Core.Application.Features.AuthFeature.Commands.RegisterCommand;

public class RegisterCommandRequest : IRequest<Result<AuthResponseDto>>, IIdempotentCommand
{
    public RegisterCommandDto? RegisterCommandRequestDto { get; set; }

    public string OperationId { get; set; } = string.Empty;
    public string IdempotencyEndpointName => "auth.register";
}

