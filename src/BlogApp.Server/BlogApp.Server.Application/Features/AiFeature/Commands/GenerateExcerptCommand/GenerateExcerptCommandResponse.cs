using BlogApp.Server.Application.Common.Models;

namespace BlogApp.Server.Application.Features.AiFeature.Commands.GenerateExcerptCommand;

/// <summary>
/// Response for AI excerpt generation
/// </summary>
public class GenerateExcerptCommandResponse
{
    public Result<string> Data { get; set; } = null!;
}
