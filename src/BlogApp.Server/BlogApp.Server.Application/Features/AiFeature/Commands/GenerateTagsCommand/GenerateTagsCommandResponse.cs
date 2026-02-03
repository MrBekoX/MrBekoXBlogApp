using BlogApp.Server.Application.Common.Models;

namespace BlogApp.Server.Application.Features.AiFeature.Commands.GenerateTagsCommand;

/// <summary>
/// Response for AI tags generation
/// </summary>
public class GenerateTagsCommandResponse
{
    public Result<string[]> Data { get; set; } = null!;
}
