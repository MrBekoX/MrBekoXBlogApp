using BlogApp.Server.Application.Common.Interfaces;
using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.Features.PostFeature.DTOs;
using MediatR;

namespace BlogApp.Server.Application.Features.PostFeature.Commands.CreatePostCommand;

public class CreatePostCommandRequest : IRequest<Result<Guid>>, IIdempotentCommand
{
    public CreatePostCommandDto? CreatePostCommandRequestDto { get; set; }

    public string OperationId { get; set; } = string.Empty;
    public string IdempotencyEndpointName => "posts.create";
}

