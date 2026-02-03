using BlogApp.Server.Application.Common.Models;

namespace BlogApp.Server.Application.Features.PostFeature.Commands.UpdateAiAnalysisCommand;

/// <summary>
/// Command response for AI analysis update
/// </summary>
public class UpdateAiAnalysisCommandResponse
{
    public Result Result { get; set; } = default!;
}
