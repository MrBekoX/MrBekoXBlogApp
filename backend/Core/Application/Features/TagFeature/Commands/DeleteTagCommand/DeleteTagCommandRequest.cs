using BlogApp.Core.Application.Common.Interfaces;
using BlogApp.Core.Application.Common.Models;
using MediatR;

namespace BlogApp.Core.Application.Features.TagFeature.Commands.DeleteTagCommand;

public class DeleteTagCommandRequest : IRequest<Result<Unit>>, IIdempotentCommand
{
    public Guid Id { get; set; }

    public string OperationId { get; set; } = string.Empty;
    public string IdempotencyEndpointName => "tags.delete";
}
