using BlogApp.Server.Application.Common.Models;

namespace BlogApp.Server.Application.Features.AiFeature.Commands.ImproveContentCommand;

/// <summary>
/// Response for AI content improvement
/// </summary>
public class ImproveContentCommandResponse
{
    public Result<string> Data { get; set; } = null!;
}
