using BlogApp.Server.Application.Common.Models;

namespace BlogApp.Server.Application.Features.AiFeature.Commands.GenerateTitleCommand;

/// <summary>
/// Response for AI title generation
/// </summary>
public class GenerateTitleCommandResponse : IAiOperationResponse
{
    public string OperationId { get; set; } = string.Empty;
    public string? CorrelationId { get; set; }
    public bool IsProcessing { get; set; }
    public string? ErrorCode { get; set; }
    public string? ErrorMessage { get; set; }
    public Result<string> Data { get; set; } = null!;
}


