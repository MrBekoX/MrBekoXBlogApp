using System.Text.Json.Serialization;

namespace BlogApp.Core.Application.Common.Messaging;

/// <summary>Makale içeriği değişti (Backend → Python içerik kuyruğu). İçerik gömülmez;
/// action=updated için content_hash zorunlu, action=unpublished için yasaktır.</summary>
public sealed record ArticleContentChangedV1 : AgentPayloadBase
{
    [JsonPropertyName("article_id")]
    public required string ArticleId { get; init; }

    [JsonPropertyName("article_revision")]
    public required long ArticleRevision { get; init; }

    [JsonPropertyName("action")]
    public required string Action { get; init; }

    [JsonPropertyName("content_hash")]
    public string? ContentHash { get; init; }

    [JsonPropertyName("language")]
    public string? Language { get; init; }

    [JsonPropertyName("title")]
    public string? Title { get; init; }
}

public sealed record ContentSnapshotBatchV1 : AgentPayloadBase
{
    [JsonPropertyName("sync_id")]
    public required string SyncId { get; init; }

    [JsonPropertyName("batch_index")]
    public required long BatchIndex { get; init; }

    [JsonPropertyName("total_batches")]
    public required long TotalBatches { get; init; }

    [JsonPropertyName("items")]
    public required List<AgentContentReference> Items { get; init; }
}

public sealed record ContentSnapshotCompletedV1 : AgentPayloadBase
{
    [JsonPropertyName("sync_id")]
    public required string SyncId { get; init; }

    [JsonPropertyName("item_count")]
    public required long ItemCount { get; init; }
}

public sealed record ProfileContentChangedV1 : AgentPayloadBase
{
    [JsonPropertyName("profile_revision")]
    public required long ProfileRevision { get; init; }

    [JsonPropertyName("content_hash")]
    public required string ContentHash { get; init; }

    [JsonPropertyName("context_snapshot_reference")]
    public string? ContextSnapshotReference { get; init; }
}

public sealed record ProjectContentChangedV1 : AgentPayloadBase
{
    [JsonPropertyName("project_id")]
    public required string ProjectId { get; init; }

    [JsonPropertyName("project_revision")]
    public required long ProjectRevision { get; init; }

    [JsonPropertyName("content_hash")]
    public required string ContentHash { get; init; }

    [JsonPropertyName("context_snapshot_reference")]
    public string? ContextSnapshotReference { get; init; }
}
