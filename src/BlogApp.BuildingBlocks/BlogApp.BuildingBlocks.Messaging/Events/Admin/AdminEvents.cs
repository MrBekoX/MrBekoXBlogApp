namespace BlogApp.BuildingBlocks.Messaging.Events.Admin;

/// <summary>
/// Admin quarantine operation types
/// </summary>
public enum QuarantineStatsType
{
    Stats,
    QueueStats,
    Replay
}

/// <summary>
/// Event triggered when admin requests quarantine statistics
/// </summary>
public record AdminQuarantineStatsRequestedEvent : IntegrationEvent
{
    public override string EventType => "admin.quarantine.stats.requested";
    public AdminQuarantinePayload Payload { get; init; } = null!;
}

/// <summary>
/// Event triggered when admin requests queue statistics
/// </summary>
public record AdminQueueStatsRequestedEvent : IntegrationEvent
{
    public override string EventType => "admin.queue.stats.requested";
    public AdminQueuePayload Payload { get; init; } = null!;
}

/// <summary>
/// Event triggered when admin requests to replay quarantined messages
/// </summary>
public record AdminQuarantineReplayRequestedEvent : IntegrationEvent
{
    public override string EventType => "admin.quarantine.replay.requested";
    public AdminReplayPayload Payload { get; init; } = null!;
}

/// <summary>
/// Payload for admin quarantine stats request
/// </summary>
public record AdminQuarantinePayload
{
    public QuarantineStatsType StatsType { get; init; } = QuarantineStatsType.Stats;
    public Guid RequestedBy { get; init; }
    public DateTime RequestedAt { get; init; }
}

/// <summary>
/// Payload for admin queue stats request
/// </summary>
public record AdminQueuePayload
{
    public Guid RequestedBy { get; init; }
    public DateTime RequestedAt { get; init; }
}

/// <summary>
/// Payload for admin quarantine replay request
/// </summary>
public record AdminReplayPayload
{
    public int MaxMessages { get; init; } = 10;
    public bool DryRun { get; init; } = false;
    public List<string>? TaxonomyPrefixes { get; init; }
    public int? MaxAgeSeconds { get; init; }
    public Guid RequestedBy { get; init; }
    public DateTime RequestedAt { get; init; }
}
