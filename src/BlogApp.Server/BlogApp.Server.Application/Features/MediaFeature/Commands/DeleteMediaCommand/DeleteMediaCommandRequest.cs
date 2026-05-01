using BlogApp.Server.Application.Common.Interfaces;
using BlogApp.Server.Application.Common.Models;
using MediatR;

namespace BlogApp.Server.Application.Features.MediaFeature.Commands.DeleteMediaCommand;

public class DeleteMediaCommandRequest : IRequest<Result<Unit>>, IIdempotentCommand
{
    public required string Url { get; init; }

    public string OperationId { get; set; } = string.Empty;
    public string IdempotencyEndpointName => "media.delete";
}
