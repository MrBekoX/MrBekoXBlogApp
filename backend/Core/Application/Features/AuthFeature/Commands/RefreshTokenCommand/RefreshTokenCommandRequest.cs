using BlogApp.Core.Application.Common.Interfaces;
using BlogApp.Core.Application.Common.Models;
using BlogApp.Core.Application.Features.AuthFeature.DTOs;
using MediatR;

namespace BlogApp.Core.Application.Features.AuthFeature.Commands.RefreshTokenCommand;

public class RefreshTokenCommandRequest : IRequest<Result<AuthResponseDto>>, IIdempotentCommand
{
    public RefreshTokenCommandDto? RefreshTokenCommandRequestDto { get; set; }

    public string OperationId { get; set; } = string.Empty;
    public string IdempotencyEndpointName => "auth.refresh-token";
    public string? CustomRequestHash { get; set; }
}

