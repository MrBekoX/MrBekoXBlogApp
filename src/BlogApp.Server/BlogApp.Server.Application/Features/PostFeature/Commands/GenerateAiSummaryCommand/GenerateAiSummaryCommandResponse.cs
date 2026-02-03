using BlogApp.Server.Application.Common.Models;

namespace BlogApp.Server.Application.Features.PostFeature.Commands.GenerateAiSummaryCommand;

/// <summary>
/// Response for AI summary generation (async via RabbitMQ)
/// </summary>
public class GenerateAiSummaryCommandResponse
{
    public Result Result { get; set; } = null!;
    
    /// <summary>
    /// Summary text (null for async requests, delivered via SignalR)
    /// </summary>
    public string? Summary { get; set; }
    
    /// <summary>
    /// Word count of the original content
    /// </summary>
    public int WordCount { get; set; }
    
    /// <summary>
    /// Correlation ID for tracking the async request
    /// </summary>
    public string? CorrelationId { get; set; }
    
    /// <summary>
    /// Status message
    /// </summary>
    public string? Message { get; set; }
}
