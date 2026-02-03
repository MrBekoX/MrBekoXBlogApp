using MediatR;

namespace BlogApp.Server.Application.Features.AiFeature.Commands.GenerateTagsCommand;

/// <summary>
/// Command request for generating AI tags
/// </summary>
public class GenerateTagsCommandRequest : IRequest<GenerateTagsCommandResponse>
{
    public string Content { get; set; } = string.Empty;
    public Guid UserId { get; set; }
}
