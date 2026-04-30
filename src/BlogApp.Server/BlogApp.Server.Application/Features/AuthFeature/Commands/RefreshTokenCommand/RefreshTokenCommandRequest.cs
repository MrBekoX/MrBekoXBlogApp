using BlogApp.Server.Application.Common.Interfaces;
using BlogApp.Server.Application.Features.AuthFeature.DTOs;
using MediatR;

namespace BlogApp.Server.Application.Features.AuthFeature.Commands.RefreshTokenCommand;

public class RefreshTokenCommandRequest : IRequest<RefreshTokenCommandResponse>, IIdempotentCommand
{
    public RefreshTokenCommandDto? RefreshTokenCommandRequestDto { get; set; }

    public string OperationId { get; set; } = string.Empty;
    public string IdempotencyEndpointName => "auth.refresh-token";
    public string? CustomRequestHash { get; set; }
}

