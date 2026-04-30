using BlogApp.Server.Application.Common.Interfaces;
using MediatR;

namespace BlogApp.Server.Application.Features.PostFeature.Commands.PublishPostCommand;

public class PublishPostCommandRequest : IRequest<PublishPostCommandResponse>, IIdempotentCommand
{
    public Guid Id { get; set; }
    public string OperationId { get; set; } = string.Empty;
    public string IdempotencyEndpointName => "posts.publish";
}

public class UnpublishPostCommandRequest : IRequest<UnpublishPostCommandResponse>, IIdempotentCommand
{
    public Guid Id { get; set; }
    public string OperationId { get; set; } = string.Empty;
    public string IdempotencyEndpointName => "posts.unpublish";
}


