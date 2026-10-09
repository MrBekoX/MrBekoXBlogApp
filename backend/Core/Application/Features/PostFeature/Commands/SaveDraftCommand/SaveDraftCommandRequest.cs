using BlogApp.Core.Application.Common.Interfaces;
using BlogApp.Core.Application.Common.Models;
using BlogApp.Core.Application.Features.PostFeature.DTOs;
using MediatR;

namespace BlogApp.Core.Application.Features.PostFeature.Commands.SaveDraftCommand;

public class SaveDraftCommandRequest : IRequest<Result<Guid>>, IIdempotentCommand
{
    public SaveDraftCommandDto? SaveDraftCommandRequestDto { get; set; }

    public string OperationId { get; set; } = string.Empty;
    public string IdempotencyEndpointName => "posts.save-draft";
}

