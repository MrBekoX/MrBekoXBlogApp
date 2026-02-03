using BlogApp.BuildingBlocks.Messaging.Abstractions;

namespace BlogApp.BuildingBlocks.Messaging.Events.Ai;

/// <summary>
/// Event triggered when AI content improvement is requested
/// </summary>
public record AiContentImprovementRequestedEvent : IntegrationEvent
{
    public AiContentImprovementPayload Payload { get; init; } = null!;
}

/// <summary>
/// Payload for AI content improvement request
/// </summary>
public record AiContentImprovementPayload
{
    public string Content { get; init; } = string.Empty;
    public Guid UserId { get; init; }
    public DateTime RequestedAt { get; init; }
    public string Language { get; init; } = "tr";
}
