using BlogApp.Core.Application.Common.Interfaces;
using BlogApp.Core.Application.Common.Models;
using MediatR;

namespace BlogApp.Core.Application.Features.PostFeature.Commands.DeletePostCommand;

public class DeletePostCommandRequest : IRequest<Result<Unit>>, IIdempotentCommand
{
    public Guid Id { get; set; }

    public string OperationId { get; set; } = string.Empty;
    public string IdempotencyEndpointName => "posts.delete";
}

