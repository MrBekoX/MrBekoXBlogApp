using MediatR;

namespace BlogApp.Server.Application.Features.PostFeature.Commands.DeletePostCommand;

public class DeletePostCommandRequest : IRequest<DeletePostCommandResponse>
{
    public Guid Id { get; set; }
}

