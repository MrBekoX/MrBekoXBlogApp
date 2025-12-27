using BlogApp.Server.Application.Features.PostFeature.DTOs;
using MediatR;

namespace BlogApp.Server.Application.Features.PostFeature.Commands.UpdatePostCommand;

public class UpdatePostCommandRequest : IRequest<UpdatePostCommandResponse>
{
    public UpdatePostCommandDto? UpdatePostCommandRequestDto { get; set; }
}
