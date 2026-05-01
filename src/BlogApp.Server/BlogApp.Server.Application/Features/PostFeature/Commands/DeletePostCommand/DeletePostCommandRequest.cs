using BlogApp.Server.Application.Common.Interfaces;
using BlogApp.Server.Application.Common.Models;
using MediatR;

namespace BlogApp.Server.Application.Features.PostFeature.Commands.DeletePostCommand;

public class DeletePostCommandRequest : IRequest<Result<Unit>>, IIdempotentCommand
{
    public Guid Id { get; set; }

    public string OperationId { get; set; } = string.Empty;
    public string IdempotencyEndpointName => "posts.delete";
}

