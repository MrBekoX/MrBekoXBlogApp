using System.Text.Json.Serialization;

namespace BlogApp.Core.Application.Common.Messaging;

// Mesaj türü DTO'ları (plan satır 202-217 listesi). Alan adları JSON sözleşmesindeki
// snake_case adlardır; kural kümesi AgentMessageTypeRegistry ve payload şemalarıyla ortaktır.

/// <summary>Backend → Python intake. Kullanıcı/oturum referansı (UserRef) backend tarafından eklenir;
/// bu alanın varlığı tek başına yetki kanıtı değildir (plan satır 198).</summary>
public sealed record AgentExecutionRequestedV1 : AgentPayloadBase
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
}

public sealed record AgentCancellationRequestedV1 : AgentPayloadBase
{
    [JsonPropertyName("reason")]
    public string? Reason { get; init; }
}

public sealed record AgentResumeRequestedV1 : AgentPayloadBase
{
    [JsonPropertyName("checkpoint_reference")]
    public required string CheckpointReference { get; init; }

    [JsonPropertyName("user_ref")]
    public required string UserRef { get; init; }
}

public sealed record AgentActionResultV1 : AgentPayloadBase
{
    [JsonPropertyName("proposal_id")]
    public required string ProposalId { get; init; }

    [JsonPropertyName("outcome")]
    public required string Outcome { get; init; }

    [JsonPropertyName("reason")]
    public string? Reason { get; init; }

    [JsonPropertyName("applied_article_revision")]
    public long? AppliedArticleRevision { get; init; }

    [JsonPropertyName("validated_at")]
    public required string ValidatedAt { get; init; }
}

/// <summary>Run olaylarının ortak sıra alanları: event_sequence monoton artar; execution_attempt
/// agent yürütme denemesidir ve zarf delivery_attempt (transport tekrarı) ile karıştırılmaz.</summary>
public abstract record AgentRunEventPayloadBase : AgentPayloadBase
{
    [JsonPropertyName("event_sequence")]
    public required long EventSequence { get; init; }

    [JsonPropertyName("execution_attempt")]
    public long? ExecutionAttempt { get; init; }

    [JsonPropertyName("fencing_token")]
    public string? FencingToken { get; init; }
}

public sealed record AgentRunAcceptedV1 : AgentRunEventPayloadBase
{
    [JsonPropertyName("accepted_at")]
    public required string AcceptedAt { get; init; }
}

public sealed record AgentRunModeSelectedV1 : AgentRunEventPayloadBase
{
    [JsonPropertyName("selected_mode")]
    public required string SelectedMode { get; init; }

    [JsonPropertyName("requires_web_search")]
    public required bool RequiresWebSearch { get; init; }

    [JsonPropertyName("reason")]
    public required string Reason { get; init; }
}

public sealed record AgentRunProgressedV1 : AgentRunEventPayloadBase
{
    [JsonPropertyName("kind")]
    public required string Kind { get; init; }

    [JsonPropertyName("message")]
    public required string Message { get; init; }

    [JsonPropertyName("detail")]
    public Dictionary<string, string>? Detail { get; init; }
}

public sealed record AgentRunNeedsInputV1 : AgentRunEventPayloadBase
{
    [JsonPropertyName("unresolved_questions")]
    public required List<string> UnresolvedQuestions { get; init; }

    [JsonPropertyName("usage")]
    public AgentUsageRecord? Usage { get; init; }
}

public sealed record AgentRunCompletedV1 : AgentRunEventPayloadBase
{
    [JsonPropertyName("selected_mode")]
    public required string SelectedMode { get; init; }

    [JsonPropertyName("answer")]
    public string? Answer { get; init; }

    [JsonPropertyName("report")]
    public string? Report { get; init; }

    [JsonPropertyName("citations")]
    public List<AgentSourceReference>? Citations { get; init; }

    [JsonPropertyName("source_scope")]
    public required string SourceScope { get; init; }

    [JsonPropertyName("unresolved_questions")]
    public List<string>? UnresolvedQuestions { get; init; }

    [JsonPropertyName("usage")]
    public required AgentUsageRecord Usage { get; init; }

    [JsonPropertyName("action_proposal")]
    public AgentActionProposalContent? ActionProposal { get; init; }
}

public sealed record AgentRunPartiallyCompletedV1 : AgentRunEventPayloadBase
{
    [JsonPropertyName("selected_mode")]
    public required string SelectedMode { get; init; }

    [JsonPropertyName("answer")]
    public string? Answer { get; init; }

    [JsonPropertyName("report")]
    public string? Report { get; init; }

    [JsonPropertyName("citations")]
    public List<AgentSourceReference>? Citations { get; init; }

    [JsonPropertyName("source_scope")]
    public required string SourceScope { get; init; }

    [JsonPropertyName("unresolved_questions")]
    public List<string>? UnresolvedQuestions { get; init; }

    [JsonPropertyName("usage")]
    public required AgentUsageRecord Usage { get; init; }
}

public sealed record AgentRunFailedV1 : AgentRunEventPayloadBase
{
    [JsonPropertyName("error_code")]
    public required string ErrorCode { get; init; }

    [JsonPropertyName("error_message")]
    public string? ErrorMessage { get; init; }

    [JsonPropertyName("selected_mode")]
    public string? SelectedMode { get; init; }

    [JsonPropertyName("usage")]
    public AgentUsageRecord? Usage { get; init; }
}

public sealed record AgentRunCancelledV1 : AgentRunEventPayloadBase
{
    [JsonPropertyName("reason")]
    public string? Reason { get; init; }

    [JsonPropertyName("usage")]
    public AgentUsageRecord? Usage { get; init; }
}

public sealed record AgentActionProposedV1 : AgentRunEventPayloadBase
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
