using BlogApp.BuildingBlocks.Messaging.Abstractions;

namespace BlogApp.BuildingBlocks.Messaging.Events.Ai;

/// <summary>
/// Event triggered when AI title generation is requested
/// </summary>
public record AiTitleGenerationRequestedEvent : IntegrationEvent
{
    public override string EventType => "ai.title.generation.requested";
    public AiTitleGenerationPayload Payload { get; init; } = null!;
}

/// <summary>
/// Payload for AI title generation request
/// </summary>
public record AiTitleGenerationPayload
{
    public string Content { get; init; } = string.Empty;
    public Guid UserId { get; init; }
    public DateTime RequestedAt { get; init; }
    public string Language { get; init; } = "tr";
}
