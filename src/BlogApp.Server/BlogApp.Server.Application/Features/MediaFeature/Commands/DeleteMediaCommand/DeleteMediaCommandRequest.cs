using BlogApp.Server.Application.Common.Interfaces;
using MediatR;

namespace BlogApp.Server.Application.Features.MediaFeature.Commands.DeleteMediaCommand;

public class DeleteMediaCommandRequest : IRequest<DeleteMediaCommandResponse>, IIdempotentCommand
{
    public required string Url { get; init; }

    public string OperationId { get; set; } = string.Empty;
    public string IdempotencyEndpointName => "media.delete";
}
