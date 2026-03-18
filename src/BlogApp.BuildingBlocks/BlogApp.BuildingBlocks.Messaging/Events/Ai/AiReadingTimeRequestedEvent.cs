using BlogApp.BuildingBlocks.Messaging.Abstractions;

namespace BlogApp.BuildingBlocks.Messaging.Events.Ai;

/// <summary>
/// Event triggered when AI reading time calculation is requested
/// </summary>
public record AiReadingTimeRequestedEvent : IntegrationEvent
{
    public override string EventType => "ai.reading-time.requested";
    public AiReadingTimePayload Payload { get; init; } = null!;
}

/// <summary>
/// Payload for AI reading time calculation request
/// </summary>
public record AiReadingTimePayload
{
    public string Content { get; init; } = string.Empty;
    public Guid UserId { get; init; }
    public DateTime RequestedAt { get; init; }
    public string Language { get; init; } = "tr";
}

/// <summary>
/// Event triggered when AI reading time calculation is completed
/// </summary>
public record AiReadingTimeCompletedEvent : IntegrationEvent
{
    public override string EventType => "ai.reading-time.completed";
    public AiReadingTimeResultPayload Payload { get; init; } = null!;
}

/// <summary>
/// Result payload for AI reading time completed
/// </summary>
public record AiReadingTimeResultPayload
{
    public string RequestId { get; init; } = string.Empty;
    public int ReadingTimeMinutes { get; init; }
    public int WordCount { get; init; }
}
