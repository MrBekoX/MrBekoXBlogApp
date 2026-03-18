namespace BlogApp.Server.Application.Features.AdminFeature.DTOs;

public record QuarantineStatsResponseDto
{
    public bool Ready { get; init; }
    public string Queue { get; init; } = string.Empty;
    public string? RoutingKey { get; init; }
    public int? MessageCount { get; init; }
    public int? ConsumerCount { get; init; }
    public string? Error { get; init; }
}

public record QueueStatsResponseDto
{
    public bool Ready { get; init; }
    public string Queue { get; init; } = string.Empty;
    public int? MessageCount { get; init; }
    public int? ConsumerCount { get; init; }
    public bool BacklogOverThreshold { get; init; }
    public int WarnThreshold { get; init; }
    public string? ObservedAt { get; init; }
    public string? Error { get; init; }
}

public record QuarantineReplayResponseDto
{
    public bool Success { get; init; }
    public int MessagesReplayed { get; init; }
    public int MessagesFound { get; init; }
    public bool DryRun { get; init; }
    public List<QuarantineReplayItemDto>? ReplayedItems { get; init; }
    public string? Error { get; init; }
}

public record QuarantineReplayItemDto
{
    public string? Taxonomy { get; init; }
    public int AgeSeconds { get; init; }
    public bool Replayed { get; init; }
    public string? Error { get; init; }
}

public record ReplayQuarantineCommandDto
{
    public int MaxMessages { get; init; } = 10;
    public bool DryRun { get; init; } = false;
    public List<string>? TaxonomyPrefixes { get; init; }
    public int? MaxAgeSeconds { get; init; }
}
