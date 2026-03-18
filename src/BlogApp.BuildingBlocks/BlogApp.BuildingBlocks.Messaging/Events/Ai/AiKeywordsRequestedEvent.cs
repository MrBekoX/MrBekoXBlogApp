using BlogApp.BuildingBlocks.Messaging.Abstractions;

namespace BlogApp.BuildingBlocks.Messaging.Events.Ai;

/// <summary>
/// Event triggered when AI keywords extraction is requested
/// </summary>
public record AiKeywordsRequestedEvent : IntegrationEvent
{
    public override string EventType => "ai.keywords.requested";
    public AiKeywordsPayload Payload { get; init; } = null!;
}

/// <summary>
/// Payload for AI keywords extraction request
/// </summary>
public record AiKeywordsPayload
{
    public string Content { get; init; } = string.Empty;
    public Guid UserId { get; init; }
    public int MaxKeywords { get; init; } = 10;
    public DateTime RequestedAt { get; init; }
    public string Language { get; init; } = "tr";
}

/// <summary>
/// Event triggered when AI keywords extraction is completed
/// </summary>
public record AiKeywordsCompletedEvent : IntegrationEvent
{
    public override string EventType => "ai.keywords.completed";
    public AiKeywordsResultPayload Payload { get; init; } = null!;
}

/// <summary>
/// Result payload for AI keywords completed
/// </summary>
public record AiKeywordsResultPayload
{
    public string RequestId { get; init; } = string.Empty;
    public string[] Keywords { get; init; } = [];
}
