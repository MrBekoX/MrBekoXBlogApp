using MediatR;

namespace BlogApp.Server.Application.Features.AiFeature.Commands.ImproveContentCommand;

/// <summary>
/// Command request for improving AI content
/// </summary>
public class ImproveContentCommandRequest : IRequest<ImproveContentCommandResponse>
{
    public string Content { get; set; } = string.Empty;
    public Guid UserId { get; set; }
}
