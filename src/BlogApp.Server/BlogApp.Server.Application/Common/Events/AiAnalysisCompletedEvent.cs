using BlogApp.BuildingBlocks.Messaging.Events;

namespace BlogApp.Server.Application.Common.Events;

/// <summary>
/// Event published by AI Agent when analysis is completed.
/// Backend consumes this event to update the post with AI analysis results.
/// </summary>
public record AiAnalysisCompletedEvent : IntegrationEvent
{
    public override string EventType => "ai.analysis.completed";

    /// <summary>
    /// AI analysis result payload
    /// </summary>
    public AiAnalysisResultPayload Payload { get; init; } = new();
}

/// <summary>
/// Payload containing AI analysis results
/// </summary>
public record AiAnalysisResultPayload
{
    /// <summary>
    /// Post ID that was analyzed
    /// </summary>
    public Guid PostId { get; init; }

    /// <summary>
    /// Generated summary of the article
    /// </summary>
    public string Summary { get; init; } = string.Empty;

    /// <summary>
    /// Extracted keywords
    /// </summary>
    public List<string> Keywords { get; init; } = [];

    /// <summary>
    /// SEO meta description
    /// </summary>
    public string SeoDescription { get; init; } = string.Empty;

    /// <summary>
    /// Estimated reading time in minutes
    /// </summary>
    public double ReadingTime { get; init; }

    /// <summary>
    /// Sentiment analysis result (positive, negative, neutral)
    /// </summary>
    public string Sentiment { get; init; } = string.Empty;

    /// <summary>
    /// GEO optimization data (optional)
    /// </summary>
    public AiGeoOptimizationPayload? GeoOptimization { get; init; }
}

/// <summary>
/// GEO optimization payload from AI analysis
/// </summary>
public record AiGeoOptimizationPayload
{
    public string OptimizedTitle { get; init; } = string.Empty;
    public string MetaDescription { get; init; } = string.Empty;
    public List<string> GeoKeywords { get; init; } = [];
    public string CulturalAdaptations { get; init; } = string.Empty;
    public string LanguageAdjustments { get; init; } = string.Empty;
    public string TargetAudience { get; init; } = string.Empty;
}

/// <summary>
/// Event published by Backend to request AI analysis.
/// AI Agent consumes this event to start analysis.
/// </summary>
public record ArticleAnalysisRequestedEvent : IntegrationEvent
{
    public override string EventType => "ai.analysis.requested";

    /// <summary>
    /// Article payload containing content to analyze
    /// </summary>
    public ArticlePayload Payload { get; init; } = new();
}
