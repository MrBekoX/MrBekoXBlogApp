using BlogApp.Core.Application.Common.Interfaces;
using BlogApp.Core.Application.Common.Models;
using BlogApp.Core.Application.Features.PostFeature.DTOs;
using MediatR;

namespace BlogApp.Core.Application.Features.PostFeature.Commands.UpdatePostCommand;

public class UpdatePostCommandRequest : IRequest<Result<Unit>>, IIdempotentCommand
{
    public UpdatePostCommandDto? UpdatePostCommandRequestDto { get; set; }

    public string OperationId { get; set; } = string.Empty;
    public string IdempotencyEndpointName => "posts.update";
}

