using BlogApp.Server.Application.Common.Models;

namespace BlogApp.Server.Application.Features.AiFeature.Commands.GenerateTitleCommand;

/// <summary>
/// Response for AI title generation
/// </summary>
public class GenerateTitleCommandResponse
{
    public Result<string> Data { get; set; } = null!;
}
