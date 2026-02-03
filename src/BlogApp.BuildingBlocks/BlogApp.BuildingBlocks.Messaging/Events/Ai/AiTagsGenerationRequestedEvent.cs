using BlogApp.BuildingBlocks.Messaging.Abstractions;

namespace BlogApp.BuildingBlocks.Messaging.Events.Ai;

/// <summary>
/// Event triggered when AI tags generation is requested
/// </summary>
public record AiTagsGenerationRequestedEvent : IntegrationEvent
{
    public AiTagsGenerationPayload Payload { get; init; } = null!;
}

/// <summary>
/// Payload for AI tags generation request
/// </summary>
public record AiTagsGenerationPayload
{
    public string Content { get; init; } = string.Empty;
    public Guid UserId { get; init; }
    public DateTime RequestedAt { get; init; }
    public string Language { get; init; } = "tr";
}
