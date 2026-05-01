using BlogApp.Server.Application.Common.Interfaces;
using BlogApp.Server.Application.Common.Models;
using MediatR;

namespace BlogApp.Server.Application.Features.AuthFeature.Commands.LogoutCommand;

public class LogoutCommandRequest : IRequest<Result<Unit>>, IIdempotentCommand
{
    public string? RefreshToken { get; set; }
    public string? AccessToken { get; set; }
    public string? IpAddress { get; set; }

    public string OperationId { get; set; } = string.Empty;
    public string IdempotencyEndpointName => "auth.logout";
}
