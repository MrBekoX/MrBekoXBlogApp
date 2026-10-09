using BlogApp.Core.Application.Common.Interfaces;
using BlogApp.Core.Application.Common.Models;
using MediatR;

namespace BlogApp.Core.Application.Features.PostFeature.Commands.PublishPostCommand;

public class PublishPostCommandRequest : IRequest<Result<Unit>>, IIdempotentCommand
{
    public Guid Id { get; set; }
    public string OperationId { get; set; } = string.Empty;
    public string IdempotencyEndpointName => "posts.publish";
}

public class UnpublishPostCommandRequest : IRequest<Result<Unit>>, IIdempotentCommand
{
    public Guid Id { get; set; }
    public string OperationId { get; set; } = string.Empty;
    public string IdempotencyEndpointName => "posts.unpublish";
}


