using System.Text.Json.Serialization;

namespace BlogApp.Core.Application.Common.Messaging;

// v2 run mesaj DTO'ları (src/contracts/agent/v2/payloads). Yalnız şekli değişen beş tür için
// ayrı DTO vardır; şekli v1 ile aynı olan türler (cancel, resume, action.result, accepted,
// progressed, needs_input, cancelled, action.proposed) v1 DTO'sunu paylaşır — alan kuralları
// registry'de sürüm başına ayrıdır.

/// <summary>Pinlenmiş profil sürümü referansı (common.schema.json $defs/profile_snapshot_ref).
/// Gövde taşımaz; {profile_id, revision, content_hash} üçlüsü profil kaynağını kimliklendirir.</summary>
public sealed record AgentProfileSnapshotRef : AgentPayloadBase
{
    [JsonPropertyName("profile_id")]
    public required string ProfileId { get; init; }

    [JsonPropertyName("revision")]
    public required long Revision { get; init; }

    [JsonPropertyName("content_hash")]
    public required string ContentHash { get; init; }

    /// <summary>Kimlik eşitliği (ExtensionData hariç; record eşitliği sözlük referansını da karşılaştırır).</summary>
    public bool SameAs(AgentProfileSnapshotRef? other) =>
        other is not null
        && string.Equals(ProfileId, other.ProfileId, StringComparison.Ordinal)
        && Revision == other.Revision
        && string.Equals(ContentHash, other.ContentHash, StringComparison.Ordinal);
}

/// <summary>v2 SourceReference: article | web | profile. Tür bazlı alan ayrımı doğrulayıcıda
/// uygulanır (profile: source_id/title/profile_*/section_id/chunk_index/url zorunlu).</summary>
public sealed record AgentSourceReferenceV2 : AgentPayloadBase
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

    [JsonPropertyName("profile_id")]
    public string? ProfileId { get; init; }

    [JsonPropertyName("profile_revision")]
    public long? ProfileRevision { get; init; }

    [JsonPropertyName("profile_content_hash")]
    public string? ProfileContentHash { get; init; }

    [JsonPropertyName("section_id")]
    public string? SectionId { get; init; }
}

/// <summary>v2 execute: v1 alanları + conversation_topic (zorunlu) + profile_snapshot
/// (who_am_i'de zorunlu; who_am_i makale üçlüsü ve selected_text taşıyamaz).</summary>
public sealed record AgentExecutionRequestedV2 : AgentPayloadBase
{
    [JsonPropertyName("user_ref")]
    public required string UserRef { get; init; }

    [JsonPropertyName("question")]
    public required string Question { get; init; }

    [JsonPropertyName("language")]
    public required string Language { get; init; }

    [JsonPropertyName("mode_preference")]
    public required string ModePreference { get; init; }

    [JsonPropertyName("budget_profile")]
    public required string BudgetProfile { get; init; }

    [JsonPropertyName("article_id")]
    public string? ArticleId { get; init; }

    [JsonPropertyName("article_revision")]
    public long? ArticleRevision { get; init; }

    [JsonPropertyName("article_content_hash")]
    public string? ArticleContentHash { get; init; }

    [JsonPropertyName("context_snapshot_reference")]
    public string? ContextSnapshotReference { get; init; }

    [JsonPropertyName("selected_text")]
    public string? SelectedText { get; init; }

    [JsonPropertyName("conversation_history")]
    public List<AgentConversationTurn>? ConversationHistory { get; init; }

    [JsonPropertyName("conversation_topic")]
    public required string ConversationTopic { get; init; }

    [JsonPropertyName("profile_snapshot")]
    public AgentProfileSnapshotRef? ProfileSnapshot { get; init; }
}

/// <summary>v2 mode_selected: router kararı + etkin niyet/kaynak kapsamı (AUTO→PROFILE
/// kararı backend'e doğrulanabilir taşınır).</summary>
public sealed record AgentRunModeSelectedV2 : AgentRunEventPayloadBase
{
    [JsonPropertyName("selected_mode")]
    public required string SelectedMode { get; init; }

    [JsonPropertyName("requires_web_search")]
    public required bool RequiresWebSearch { get; init; }

    [JsonPropertyName("reason")]
    public required string Reason { get; init; }

    [JsonPropertyName("run_intent")]
    public required string RunIntent { get; init; }

    [JsonPropertyName("source_scope")]
    public required string SourceScope { get; init; }

    [JsonPropertyName("profile_snapshot")]
    public AgentProfileSnapshotRef? ProfileSnapshot { get; init; }
}

public sealed record AgentRunCompletedV2 : AgentRunEventPayloadBase
{
    [JsonPropertyName("selected_mode")]
    public required string SelectedMode { get; init; }

    [JsonPropertyName("answer")]
    public string? Answer { get; init; }

    [JsonPropertyName("report")]
    public string? Report { get; init; }

    [JsonPropertyName("citations")]
    public List<AgentSourceReferenceV2>? Citations { get; init; }

    [JsonPropertyName("source_scope")]
    public required string SourceScope { get; init; }

    [JsonPropertyName("unresolved_questions")]
    public List<string>? UnresolvedQuestions { get; init; }

    [JsonPropertyName("usage")]
    public required AgentUsageRecord Usage { get; init; }

    [JsonPropertyName("action_proposal")]
    public AgentActionProposalContent? ActionProposal { get; init; }

    [JsonPropertyName("run_intent")]
    public required string RunIntent { get; init; }

    [JsonPropertyName("profile_snapshot")]
    public AgentProfileSnapshotRef? ProfileSnapshot { get; init; }
}

public sealed record AgentRunPartiallyCompletedV2 : AgentRunEventPayloadBase
{
    [JsonPropertyName("selected_mode")]
    public required string SelectedMode { get; init; }

    [JsonPropertyName("answer")]
    public string? Answer { get; init; }

    [JsonPropertyName("report")]
    public string? Report { get; init; }

    [JsonPropertyName("citations")]
    public List<AgentSourceReferenceV2>? Citations { get; init; }

    [JsonPropertyName("source_scope")]
    public required string SourceScope { get; init; }

    [JsonPropertyName("unresolved_questions")]
    public List<string>? UnresolvedQuestions { get; init; }

    [JsonPropertyName("usage")]
    public required AgentUsageRecord Usage { get; init; }

    [JsonPropertyName("run_intent")]
    public required string RunIntent { get; init; }

    [JsonPropertyName("profile_snapshot")]
    public AgentProfileSnapshotRef? ProfileSnapshot { get; init; }
}

public sealed record AgentRunFailedV2 : AgentRunEventPayloadBase
{
    [JsonPropertyName("error_code")]
    public required string ErrorCode { get; init; }

    [JsonPropertyName("error_message")]
    public string? ErrorMessage { get; init; }

    [JsonPropertyName("selected_mode")]
    public string? SelectedMode { get; init; }

    [JsonPropertyName("usage")]
    public AgentUsageRecord? Usage { get; init; }

    [JsonPropertyName("run_intent")]
    public string? RunIntent { get; init; }

    [JsonPropertyName("profile_snapshot")]
    public AgentProfileSnapshotRef? ProfileSnapshot { get; init; }
}
