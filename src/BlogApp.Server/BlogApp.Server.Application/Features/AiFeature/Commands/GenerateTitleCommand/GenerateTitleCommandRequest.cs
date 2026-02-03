using MediatR;

namespace BlogApp.Server.Application.Features.AiFeature.Commands.GenerateTitleCommand;

/// <summary>
/// Command request for generating AI title
/// </summary>
public class GenerateTitleCommandRequest : IRequest<GenerateTitleCommandResponse>
{
    public string Content { get; set; } = string.Empty;
    public Guid UserId { get; set; }
}
