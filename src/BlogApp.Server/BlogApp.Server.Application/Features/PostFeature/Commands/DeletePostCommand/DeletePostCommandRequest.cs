using BlogApp.Server.Application.Common.Interfaces;
using MediatR;

namespace BlogApp.Server.Application.Features.PostFeature.Commands.DeletePostCommand;

public class DeletePostCommandRequest : IRequest<DeletePostCommandResponse>, IIdempotentCommand
{
    public Guid Id { get; set; }

    public string OperationId { get; set; } = string.Empty;
    public string IdempotencyEndpointName => "posts.delete";
}

