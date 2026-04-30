using BlogApp.Server.Application.Common.Interfaces;
using MediatR;

namespace BlogApp.Server.Application.Features.TagFeature.Commands.DeleteTagCommand;

public class DeleteTagCommandRequest : IRequest<DeleteTagCommandResponse>, IIdempotentCommand
{
    public Guid Id { get; set; }

    public string OperationId { get; set; } = string.Empty;
    public string IdempotencyEndpointName => "tags.delete";
}

