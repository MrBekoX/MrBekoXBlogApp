using BlogApp.Server.Application.Common.Models;

namespace BlogApp.Server.Application.Features.AiFeature.Commands.CalculateReadingTimeCommand;

/// <summary>
/// Response for reading time calculation
/// </summary>
public class CalculateReadingTimeCommandResponse : IAiOperationResponse
{
    public string OperationId { get; set; } = string.Empty;
    public string? CorrelationId { get; set; }
    public bool IsProcessing { get; set; }
    public string? ErrorCode { get; set; }
    public string? ErrorMessage { get; set; }
    public Result<ReadingTimeResult> Data { get; set; } = null!;
}

/// <summary>
/// Reading time calculation result
/// </summary>
public class ReadingTimeResult : IAiOperationResponse
{
    public string OperationId { get; set; } = string.Empty;
    public string? CorrelationId { get; set; }
    public bool IsProcessing { get; set; }
    public string? ErrorCode { get; set; }
    public string? ErrorMessage { get; set; }
    public int ReadingTimeMinutes { get; set; }
    public int WordCount { get; set; }
}


