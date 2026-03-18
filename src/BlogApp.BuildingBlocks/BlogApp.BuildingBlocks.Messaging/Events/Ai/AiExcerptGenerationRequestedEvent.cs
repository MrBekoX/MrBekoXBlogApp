using BlogApp.BuildingBlocks.Messaging.Abstractions;

namespace BlogApp.BuildingBlocks.Messaging.Events.Ai;

/// <summary>
/// Event triggered when AI excerpt generation is requested
/// </summary>
public record AiExcerptGenerationRequestedEvent : IntegrationEvent
{
    public override string EventType => "ai.excerpt.generation.requested";
    public AiExcerptGenerationPayload Payload { get; init; } = null!;
}

/// <summary>
/// Payload for AI excerpt generation request
/// </summary>
public record AiExcerptGenerationPayload
{
    public string Content { get; init; } = string.Empty;
    public Guid UserId { get; init; }
    public DateTime RequestedAt { get; init; }
    public string Language { get; init; } = "tr";
}
