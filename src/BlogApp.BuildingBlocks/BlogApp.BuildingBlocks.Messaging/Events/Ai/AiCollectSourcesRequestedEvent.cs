using BlogApp.BuildingBlocks.Messaging.Abstractions;

namespace BlogApp.BuildingBlocks.Messaging.Events.Ai;

/// <summary>
/// Event triggered when AI web source collection is requested
/// </summary>
public record AiCollectSourcesRequestedEvent : IntegrationEvent
{
    public override string EventType => "ai.collect-sources.requested";
    public AiCollectSourcesPayload Payload { get; init; } = null!;
}

/// <summary>
/// Payload for AI web source collection request
/// </summary>
public record AiCollectSourcesPayload
{
    public string Query { get; init; } = string.Empty;
    public Guid UserId { get; init; }
    public int MaxSources { get; init; } = 5;
    public DateTime RequestedAt { get; init; }
    public string Language { get; init; } = "tr";
}

/// <summary>
/// Event triggered when AI web source collection is completed
/// </summary>
public record AiCollectSourcesCompletedEvent : IntegrationEvent
{
    public override string EventType => "ai.collect-sources.completed";
    public AiCollectSourcesResultPayload Payload { get; init; } = null!;
}

/// <summary>
/// Result payload for AI web source collection completed
/// </summary>
public record AiCollectSourcesResultPayload
{
    public string RequestId { get; init; } = string.Empty;
    public WebSource[] Sources { get; init; } = [];
}

/// <summary>
/// Web source data structure
/// </summary>
public record WebSource
{
    public string Title { get; init; } = string.Empty;
    public string Url { get; init; } = string.Empty;
    public string Snippet { get; init; } = string.Empty;
}
