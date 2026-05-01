using BlogApp.Server.Application.Common.Interfaces;
using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.Features.TagFeature.DTOs;
using MediatR;

namespace BlogApp.Server.Application.Features.TagFeature.Commands.CreateTagCommand;

public class CreateTagCommandRequest : IRequest<Result<Guid>>, IIdempotentCommand
{
    public CreateTagCommandDto? CreateTagCommandRequestDto { get; set; }

    public string OperationId { get; set; } = string.Empty;
    public string IdempotencyEndpointName => "tags.create";
}
