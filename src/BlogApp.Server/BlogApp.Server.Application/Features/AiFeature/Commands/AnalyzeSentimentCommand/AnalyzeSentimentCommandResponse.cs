using BlogApp.Server.Application.Common.Models;

namespace BlogApp.Server.Application.Features.AiFeature.Commands.AnalyzeSentimentCommand;

/// <summary>
/// Response for AI sentiment analysis
/// </summary>
public class AnalyzeSentimentCommandResponse : IAiOperationResponse
{
    public string OperationId { get; set; } = string.Empty;
    public string? CorrelationId { get; set; }
    public bool IsProcessing { get; set; }
    public string? ErrorCode { get; set; }
    public string? ErrorMessage { get; set; }
    public Result<SentimentResult> Data { get; set; } = null!;
}

/// <summary>
/// Sentiment analysis result
/// </summary>
public class SentimentResult : IAiOperationResponse
{
    public string OperationId { get; set; } = string.Empty;
    public string? CorrelationId { get; set; }
    public bool IsProcessing { get; set; }
    public string? ErrorCode { get; set; }
    public string? ErrorMessage { get; set; }
    public string Sentiment { get; set; } = string.Empty;
    public double Confidence { get; set; }
}


