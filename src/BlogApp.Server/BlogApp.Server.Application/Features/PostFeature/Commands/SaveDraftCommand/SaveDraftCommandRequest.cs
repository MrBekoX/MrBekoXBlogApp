using BlogApp.Server.Application.Common.Interfaces;
using BlogApp.Server.Application.Features.PostFeature.DTOs;
using MediatR;

namespace BlogApp.Server.Application.Features.PostFeature.Commands.SaveDraftCommand;

public class SaveDraftCommandRequest : IRequest<SaveDraftCommandResponse>, IIdempotentCommand
{
    public SaveDraftCommandDto? SaveDraftCommandRequestDto { get; set; }

    public string OperationId { get; set; } = string.Empty;
    public string IdempotencyEndpointName => "posts.save-draft";
}

