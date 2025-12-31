using BlogApp.Server.Application.Features.PostFeature.DTOs;
using MediatR;

namespace BlogApp.Server.Application.Features.PostFeature.Commands.CreatePostCommand;

public class CreatePostCommandRequest : IRequest<CreatePostCommandResponse>
{
    public CreatePostCommandDto? CreatePostCommandRequestDto { get; set; }
}

