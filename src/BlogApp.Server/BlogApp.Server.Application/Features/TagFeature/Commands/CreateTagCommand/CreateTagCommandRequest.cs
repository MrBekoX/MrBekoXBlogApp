using BlogApp.Server.Application.Features.TagFeature.DTOs;
using MediatR;

namespace BlogApp.Server.Application.Features.TagFeature.Commands.CreateTagCommand;

public class CreateTagCommandRequest : IRequest<CreateTagCommandResponse>
{
    public CreateTagCommandDto? CreateTagCommandRequestDto { get; set; }
}

