using BlogApp.Server.Application.Features.PostFeature.DTOs;
using MediatR;

namespace BlogApp.Server.Application.Features.PostFeature.Commands.SaveDraftCommand;

public class SaveDraftCommandRequest : IRequest<SaveDraftCommandResponse>
{
    public SaveDraftCommandDto? SaveDraftCommandRequestDto { get; set; }
}
