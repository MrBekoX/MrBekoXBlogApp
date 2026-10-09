using BlogApp.Core.Application.Common.Interfaces;
using BlogApp.Core.Application.Common.Models;
using BlogApp.Core.Application.Features.TagFeature.DTOs;
using MediatR;

namespace BlogApp.Core.Application.Features.TagFeature.Commands.CreateTagCommand;

public class CreateTagCommandRequest : IRequest<Result<Guid>>, IIdempotentCommand
{
    public CreateTagCommandDto? CreateTagCommandRequestDto { get; set; }

    public string OperationId { get; set; } = string.Empty;
    public string IdempotencyEndpointName => "tags.create";
}
