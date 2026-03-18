using BlogApp.BuildingBlocks.Messaging.Abstractions;

namespace BlogApp.BuildingBlocks.Messaging.Events.Ai;

/// <summary>
/// Event triggered when AI GEO optimization is requested
/// </summary>
public record AiGeoOptimizeRequestedEvent : IntegrationEvent
{
    public override string EventType => "ai.geo-optimize.requested";
    public AiGeoOptimizePayload Payload { get; init; } = null!;
}

/// <summary>
/// Payload for AI GEO optimization request
/// </summary>
public record AiGeoOptimizePayload
{
    public string Content { get; init; } = string.Empty;
    public Guid UserId { get; init; }
    public string TargetRegion { get; init; } = "TR";
    public DateTime RequestedAt { get; init; }
    public string Language { get; init; } = "tr";
}

/// <summary>
/// Event triggered when AI GEO optimization is completed
/// </summary>
public record AiGeoOptimizeCompletedEvent : IntegrationEvent
{
    public override string EventType => "ai.geo-optimize.completed";
    public AiGeoOptimizeResultPayload Payload { get; init; } = null!;
}

/// <summary>
/// Result payload for AI GEO optimization completed
/// </summary>
public record AiGeoOptimizeResultPayload
{
    public string RequestId { get; init; } = string.Empty;
    public GeoOptimizationData GeoOptimization { get; init; } = null!;
}

/// <summary>
/// GEO optimization data structure
/// </summary>
public record GeoOptimizationData
{
    public string TargetRegion { get; init; } = string.Empty;
    public string LocalizedTitle { get; init; } = string.Empty;
    public string LocalizedSummary { get; init; } = string.Empty;
    public string[] LocalizedKeywords { get; init; } = [];
    public string CulturalNotes { get; init; } = string.Empty;
}
