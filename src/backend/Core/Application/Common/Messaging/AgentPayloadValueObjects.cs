using System.Text.Json;
using System.Text.Json.Serialization;

namespace BlogApp.Core.Application.Common.Messaging;

/// <summary>
/// Payload DTO tabanı: bilinmeyen alanlar ExtensionData'ya düşer; doğrulayıcı boş olmamasını zorunlu kılar
/// (sözleşme additionalProperties: false'tur).
/// </summary>
public abstract record AgentPayloadBase
{
    [JsonExtensionData]
    public Dictionary<string, JsonElement>? ExtensionData { get; init; }
}

/// <summary>A1 UsageRecord'un taşıma karşılığı; run_id zarfın run_id'siyle uyuşmak zorundadır.</summary>
public sealed record AgentUsageRecord : AgentPayloadBase
{
    [JsonPropertyName("run_id")]
    public required string RunId { get; init; }

    [JsonPropertyName("model_calls")]
    public long? ModelCalls { get; init; }

    [JsonPropertyName("prompt_tokens")]
    public long? PromptTokens { get; init; }

    [JsonPropertyName("completion_tokens")]
    public long? CompletionTokens { get; init; }

    [JsonPropertyName("total_tokens")]
    public long? TotalTokens { get; init; }

    [JsonPropertyName("tool_calls")]
    public long? ToolCalls { get; init; }

    [JsonPropertyName("web_search_calls")]
    public long? WebSearchCalls { get; init; }

    [JsonPropertyName("duration_seconds")]
    public double? DurationSeconds { get; init; }

    [JsonPropertyName("recorded_at")]
    public required string RecordedAt { get; init; }
}

/// <summary>A1 SourceReference'un taşıma karşılığı; kind'a göre alan ayrımı doğrulayıcıda uygulanır.</summary>
public sealed record AgentSourceReference : AgentPayloadBase
{
    [JsonPropertyName("kind")]
    public required string Kind { get; init; }

    [JsonPropertyName("source_id")]
    public string? SourceId { get; init; }

    [JsonPropertyName("title")]
    public string? Title { get; init; }

    [JsonPropertyName("article_id")]
    public string? ArticleId { get; init; }

    [JsonPropertyName("article_revision")]
    public long? ArticleRevision { get; init; }

    [JsonPropertyName("chunk_index")]
    public long? ChunkIndex { get; init; }

    [JsonPropertyName("url")]
    public string? Url { get; init; }

    [JsonPropertyName("accessed_at")]
    public string? AccessedAt { get; init; }
}

/// <summary>A1 ConversationTurn'un taşıma karşılığı.</summary>
public sealed record AgentConversationTurn : AgentPayloadBase
{
    [JsonPropertyName("role")]
    public required string Role { get; init; }

    [JsonPropertyName("content")]
    public required string Content { get; init; }

    [JsonPropertyName("created_at")]
    public required string CreatedAt { get; init; }
}

/// <summary>A1 ActionProposal'un taşıma karşılığı; kayıt yalnız açık gönderim onayıyla yapılar.</summary>
public sealed record AgentActionProposalContent : AgentPayloadBase
{
    [JsonPropertyName("run_id")]
    public required string RunId { get; init; }

    [JsonPropertyName("proposal_id")]
    public required string ProposalId { get; init; }

    [JsonPropertyName("article_id")]
    public required string ArticleId { get; init; }

    [JsonPropertyName("article_revision")]
    public required long ArticleRevision { get; init; }

    [JsonPropertyName("base_content_hash")]
    public required string BaseContentHash { get; init; }

    [JsonPropertyName("summary")]
    public required string Summary { get; init; }

    [JsonPropertyName("proposed_content")]
    public required string ProposedContent { get; init; }

    [JsonPropertyName("created_at")]
    public required string CreatedAt { get; init; }
}

/// <summary>İçerik senkronizasyonu toplu referans kaydı (K7: içerik gömülmez, hash referansı taşınır).</summary>
public sealed record AgentContentReference : AgentPayloadBase
{
    [JsonPropertyName("article_id")]
    public required string ArticleId { get; init; }

    [JsonPropertyName("article_revision")]
    public required long ArticleRevision { get; init; }

    [JsonPropertyName("content_hash")]
    public required string ContentHash { get; init; }
}
