using BlogApp.BuildingBlocks.Messaging.Abstractions;

namespace BlogApp.BuildingBlocks.Messaging.Events.Ai;

/// <summary>
/// Event triggered when AI summarize is requested
/// </summary>
public record AiSummarizeRequestedEvent : IntegrationEvent
{
    public override string EventType => "ai.summarize.requested";
    public AiSummarizePayload Payload { get; init; } = null!;
}

/// <summary>
/// Payload for AI summarize request
/// </summary>
public record AiSummarizePayload
{
    public string Content { get; init; } = string.Empty;
    public Guid UserId { get; init; }
    public int MaxSentences { get; init; } = 5;
    public DateTime RequestedAt { get; init; }
    public string Language { get; init; } = "tr";
}

/// <summary>
/// Event triggered when AI summarize is completed
/// </summary>
public record AiSummarizeCompletedEvent : IntegrationEvent
{
    public override string EventType => "ai.summarize.completed";
    public AiSummarizeResultPayload Payload { get; init; } = null!;
}

/// <summary>
/// Result payload for AI summarize completed
/// </summary>
public record AiSummarizeResultPayload
{
    public string RequestId { get; init; } = string.Empty;
    public string Summary { get; init; } = string.Empty;
}
