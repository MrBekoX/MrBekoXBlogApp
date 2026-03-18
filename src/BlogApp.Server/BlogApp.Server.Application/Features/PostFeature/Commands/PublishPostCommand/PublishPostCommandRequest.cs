using MediatR;

namespace BlogApp.Server.Application.Features.PostFeature.Commands.PublishPostCommand;

public class PublishPostCommandRequest : IRequest<PublishPostCommandResponse>
{
    public Guid Id { get; set; }
    public string OperationId { get; set; } = string.Empty;
}

public class UnpublishPostCommandRequest : IRequest<UnpublishPostCommandResponse>
{
    public Guid Id { get; set; }
    public string OperationId { get; set; } = string.Empty;
}


