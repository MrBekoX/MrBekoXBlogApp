using BlogApp.Server.Application.Common.Interfaces;
using BlogApp.Server.Application.Features.PostFeature.DTOs;
using MediatR;

namespace BlogApp.Server.Application.Features.PostFeature.Commands.UpdatePostCommand;

public class UpdatePostCommandRequest : IRequest<UpdatePostCommandResponse>, IIdempotentCommand
{
    public UpdatePostCommandDto? UpdatePostCommandRequestDto { get; set; }

    public string OperationId { get; set; } = string.Empty;
    public string IdempotencyEndpointName => "posts.update";
}

