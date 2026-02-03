using BlogApp.Server.Application.Common.Models;

namespace BlogApp.Server.Application.Features.AiFeature.Commands.GenerateSeoDescriptionCommand;

/// <summary>
/// Response for AI SEO description generation
/// </summary>
public class GenerateSeoDescriptionCommandResponse
{
    public Result<string> Data { get; set; } = null!;
}
