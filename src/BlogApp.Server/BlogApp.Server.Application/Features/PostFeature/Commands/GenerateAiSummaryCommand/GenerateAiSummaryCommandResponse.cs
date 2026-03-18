using BlogApp.Server.Application.Common.Models;

namespace BlogApp.Server.Application.Features.PostFeature.Commands.GenerateAiSummaryCommand;

/// <summary>
/// Response for AI summary generation.
/// </summary>
public class GenerateAiSummaryCommandResponse
{
    public string OperationId { get; set; } = string.Empty;
    public string? CorrelationId { get; set; }
    public bool IsProcessing { get; set; }
    public string? ErrorCode { get; set; }
    public string? ErrorMessage { get; set; }
    public Result Result { get; set; } = null!;
    public string? Summary { get; set; }
    public int WordCount { get; set; }
    public string? Message { get; set; }
}
