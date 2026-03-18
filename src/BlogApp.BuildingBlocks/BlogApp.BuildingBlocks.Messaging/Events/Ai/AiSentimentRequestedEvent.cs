using BlogApp.BuildingBlocks.Messaging.Abstractions;

namespace BlogApp.BuildingBlocks.Messaging.Events.Ai;

/// <summary>
/// Event triggered when AI sentiment analysis is requested
/// </summary>
public record AiSentimentRequestedEvent : IntegrationEvent
{
    public override string EventType => "ai.sentiment.requested";
    public AiSentimentPayload Payload { get; init; } = null!;
}

/// <summary>
/// Payload for AI sentiment analysis request
/// </summary>
public record AiSentimentPayload
{
    public string Content { get; init; } = string.Empty;
    public Guid UserId { get; init; }
    public DateTime RequestedAt { get; init; }
    public string Language { get; init; } = "tr";
}

/// <summary>
/// Event triggered when AI sentiment analysis is completed
/// </summary>
public record AiSentimentCompletedEvent : IntegrationEvent
{
    public override string EventType => "ai.sentiment.completed";
    public AiSentimentResultPayload Payload { get; init; } = null!;
}

/// <summary>
/// Result payload for AI sentiment completed
/// </summary>
public record AiSentimentResultPayload
{
    public string RequestId { get; init; } = string.Empty;
    public string Sentiment { get; init; } = string.Empty;
    public double Confidence { get; init; }
}
