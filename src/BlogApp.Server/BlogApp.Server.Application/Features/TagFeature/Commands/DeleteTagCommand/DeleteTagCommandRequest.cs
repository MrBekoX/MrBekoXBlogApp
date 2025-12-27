using MediatR;

namespace BlogApp.Server.Application.Features.TagFeature.Commands.DeleteTagCommand;

public class DeleteTagCommandRequest : IRequest<DeleteTagCommandResponse>
{
    public Guid Id { get; set; }
}
