using BlogApp.BuildingBlocks.Messaging.Abstractions;

namespace BlogApp.BuildingBlocks.Messaging.Events.Ai;

/// <summary>
/// Event triggered when AI SEO description generation is requested
/// </summary>
public record AiSeoDescriptionGenerationRequestedEvent : IntegrationEvent
{
    public override string EventType => "ai.seo.generation.requested";
    public AiSeoDescriptionGenerationPayload Payload { get; init; } = null!;
}

/// <summary>
/// Payload for AI SEO description generation request
/// </summary>
public record AiSeoDescriptionGenerationPayload
{
    public string Content { get; init; } = string.Empty;
    public Guid UserId { get; init; }
    public DateTime RequestedAt { get; init; }
    public string Language { get; init; } = "tr";
}
