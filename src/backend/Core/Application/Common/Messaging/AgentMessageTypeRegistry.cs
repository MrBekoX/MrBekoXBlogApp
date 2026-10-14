namespace BlogApp.Core.Application.Common.Messaging;

/// <summary>Mesaj türlerinin makine-okur adları; routing key "{ad}.v1" kuralıyla türetilir.</summary>
public static class AgentMessageTypes
{
    public const string ExecutionRequested = "agent.execute.requested";
    public const string CancellationRequested = "agent.cancel.requested";
    public const string ResumeRequested = "agent.resume.requested";
    public const string ActionResult = "agent.action.result";
    public const string RunAccepted = "agent.run.accepted";
    public const string RunModeSelected = "agent.run.mode_selected";
    public const string RunProgressed = "agent.run.progressed";
    public const string RunNeedsInput = "agent.run.needs_input";
    public const string RunCompleted = "agent.run.completed";
    public const string RunPartiallyCompleted = "agent.run.partially_completed";
    public const string RunFailed = "agent.run.failed";
    public const string RunCancelled = "agent.run.cancelled";
    public const string ActionProposed = "agent.action.proposed";
    public const string ArticleContentChanged = "content.article.changed";
    public const string SyncBatch = "content.sync.batch";
    public const string SyncCompleted = "content.sync.completed";
    public const string ProfileContentChanged = "content.profile.changed";
    public const string ProjectContentChanged = "content.project.changed";
}

public enum AgentMessageDirection
{
    BackendToAgent,
    AgentToBackend
}

/// <summary>Bir mesaj türünün sözleşme kaydı: yön, exchange/routing eşlemesi, izinli üreticiler,
/// zarf gereksinimleri ve payload kural kümesi. contract.json kaydıyla ayna testleriyle eşlenir.</summary>
public sealed record AgentMessageTypeSpec
{
    public required string MessageType { get; init; }
    public required AgentMessageDirection Direction { get; init; }
    public required string Exchange { get; init; }
    public required string RoutingKey { get; init; }
    public required IReadOnlyList<string> AllowedProducers { get; init; }
    public required bool RequiresRunIdentity { get; init; }
    public required bool RequiresDeadline { get; init; }
    public required string PayloadSchema { get; init; }
    public required Type PayloadDtoType { get; init; }
    public required IReadOnlyList<AgentFieldRule> PayloadFields { get; init; }
}

/// <summary>
/// 18 mesaj türünün tek kaynağı. Exchange'ler ve routing key'leri plan satır 219-233 tablosundan;
/// payload kuralları src/contracts/agent/v1/payloads/*.schema.json dosyalarından yansıtılmıştır.
/// </summary>
public static class AgentMessageTypeRegistry
{
    public const int SchemaVersion = 1;
    public const string ContentType = "application/json";
    public const string CommandsExchange = "blog.agent.commands";
    public const string EventsExchange = "blog.agent.events";
    public const string ContentExchange = "blog.content.events";

    public const string ProducerBackendNet = "backend-net";
    public const string ProducerAgentPy = "agent-py";
    public const string ProducerTestExecutor = "test-executor";

    public static readonly IReadOnlyList<string> AllProducers = [ProducerBackendNet, ProducerAgentPy, ProducerTestExecutor];

    private static readonly Dictionary<string, AgentMessageTypeSpec> Specs = Build().ToDictionary(s => s.MessageType, StringComparer.Ordinal);

    public static IReadOnlyCollection<AgentMessageTypeSpec> MessageTypes => Specs.Values;

    public static bool TryGet(string messageType, out AgentMessageTypeSpec spec) =>
        Specs.TryGetValue(messageType, out spec!);

    private static AgentFieldRule[] RunEventFields(params AgentFieldRule[] extra)
    {
        var fields = new List<AgentFieldRule>
        {
            AgentFieldRule.Integer("event_sequence", required: true),
            AgentFieldRule.Integer("execution_attempt", minimum: 1),
            AgentFieldRule.Text("fencing_token", maxLength: 128)
        };
        fields.AddRange(extra);
        return [.. fields];
    }

    private static AgentFieldRule UsageRule(bool required = false) =>
        AgentFieldRule.Composite("usage", required,
            AgentFieldRule.Text("run_id", required: true, maxLength: 128),
            AgentFieldRule.Integer("model_calls"),
            AgentFieldRule.Integer("prompt_tokens"),
            AgentFieldRule.Integer("completion_tokens"),
            AgentFieldRule.Integer("total_tokens"),
            AgentFieldRule.Integer("tool_calls"),
            AgentFieldRule.Integer("web_search_calls"),
            AgentFieldRule.Decimal("duration_seconds"),
            AgentFieldRule.Text("recorded_at", required: true, format: AgentFieldFormat.UtcIso));

    private static AgentFieldRule SourceReferenceRule() =>
        AgentFieldRule.Composite("kind_source_reference", false,
            AgentFieldRule.Choice("kind", required: true, "article", "web"),
            AgentFieldRule.Text("source_id", maxLength: 512),
            AgentFieldRule.Text("title", maxLength: 512),
            AgentFieldRule.Text("article_id", maxLength: 128),
            AgentFieldRule.Integer("article_revision"),
            AgentFieldRule.Integer("chunk_index"),
            AgentFieldRule.Text("url", maxLength: 2048),
            AgentFieldRule.Text("accessed_at", format: AgentFieldFormat.UtcIso)) with
        { Name = "citations_item" };

    private static AgentFieldRule ProposalRule() =>
        AgentFieldRule.Composite("action_proposal", false,
            AgentFieldRule.Text("run_id", required: true, maxLength: 128),
            AgentFieldRule.Text("proposal_id", required: true, maxLength: 128),
            AgentFieldRule.Text("article_id", required: true, maxLength: 128),
            AgentFieldRule.Integer("article_revision", required: true),
            AgentFieldRule.Text("base_content_hash", required: true, format: AgentFieldFormat.HashHex),
            AgentFieldRule.Text("summary", required: true, maxLength: 8000),
            AgentFieldRule.Text("proposed_content", required: true, maxLength: 20000),
            AgentFieldRule.Text("created_at", required: true, format: AgentFieldFormat.UtcIso));

    private static List<AgentMessageTypeSpec> Build()
    {
        var backendProducers = new List<string> { ProducerBackendNet, ProducerTestExecutor };
        var agentProducers = new List<string> { ProducerAgentPy, ProducerTestExecutor };

        return
        [
            new()
            {
                MessageType = AgentMessageTypes.ExecutionRequested,
                Direction = AgentMessageDirection.BackendToAgent,
                Exchange = CommandsExchange,
                RoutingKey = "agent.execute.requested.v1",
                AllowedProducers = backendProducers,
                RequiresRunIdentity = true,
                RequiresDeadline = true,
                PayloadSchema = "payloads/agent.execute.requested.schema.json",
                PayloadDtoType = typeof(AgentExecutionRequestedV1),
                PayloadFields =
                [
                    AgentFieldRule.Text("user_ref", required: true, maxLength: 128),
                    AgentFieldRule.Text("question", required: true, maxLength: 8000),
                    AgentFieldRule.Text("language", required: true, format: AgentFieldFormat.LanguageCode),
                    AgentFieldRule.Choice("mode_preference", required: true, "auto", "fast", "analysis", "deep_research"),
                    AgentFieldRule.Text("budget_profile", required: true, maxLength: 128),
                    AgentFieldRule.Text("article_id", maxLength: 128),
                    AgentFieldRule.Integer("article_revision"),
                    AgentFieldRule.Text("article_content_hash", format: AgentFieldFormat.HashHex),
                    AgentFieldRule.Text("context_snapshot_reference", maxLength: 512),
                    AgentFieldRule.Text("selected_text", maxLength: 20000),
                    AgentFieldRule.List("conversation_history",
                        AgentFieldRule.Composite("conversation_turn", false,
                            AgentFieldRule.Choice("role", required: true, "user", "assistant"),
                            AgentFieldRule.Text("content", required: true, maxLength: 20000),
                            AgentFieldRule.Text("created_at", required: true, format: AgentFieldFormat.UtcIso)))
                ]
            },
            new()
            {
                MessageType = AgentMessageTypes.CancellationRequested,
                Direction = AgentMessageDirection.BackendToAgent,
                Exchange = CommandsExchange,
                RoutingKey = "agent.cancel.requested.v1",
                AllowedProducers = backendProducers,
                RequiresRunIdentity = true,
                RequiresDeadline = false,
                PayloadSchema = "payloads/agent.cancel.requested.schema.json",
                PayloadDtoType = typeof(AgentCancellationRequestedV1),
                PayloadFields = [AgentFieldRule.Text("reason", maxLength: 2000)]
            },
            new()
            {
                MessageType = AgentMessageTypes.ResumeRequested,
                Direction = AgentMessageDirection.BackendToAgent,
                Exchange = CommandsExchange,
                RoutingKey = "agent.resume.requested.v1",
                AllowedProducers = backendProducers,
                RequiresRunIdentity = true,
                RequiresDeadline = false,
                PayloadSchema = "payloads/agent.resume.requested.schema.json",
                PayloadDtoType = typeof(AgentResumeRequestedV1),
                PayloadFields =
                [
                    AgentFieldRule.Text("checkpoint_reference", required: true, maxLength: 512),
                    AgentFieldRule.Text("user_ref", required: true, maxLength: 128)
                ]
            },
            new()
            {
                MessageType = AgentMessageTypes.ActionResult,
                Direction = AgentMessageDirection.BackendToAgent,
                Exchange = CommandsExchange,
                RoutingKey = "agent.action.result.v1",
                AllowedProducers = backendProducers,
                RequiresRunIdentity = true,
                RequiresDeadline = false,
                PayloadSchema = "payloads/agent.action.result.schema.json",
                PayloadDtoType = typeof(AgentActionResultV1),
                PayloadFields =
                [
                    AgentFieldRule.Text("proposal_id", required: true, maxLength: 128),
                    AgentFieldRule.Choice("outcome", required: true, "accepted", "rejected"),
                    AgentFieldRule.Text("reason", maxLength: 2000),
                    AgentFieldRule.Integer("applied_article_revision"),
                    AgentFieldRule.Text("validated_at", required: true, format: AgentFieldFormat.UtcIso)
                ]
            },
            new()
            {
                MessageType = AgentMessageTypes.RunAccepted,
                Direction = AgentMessageDirection.AgentToBackend,
                Exchange = EventsExchange,
                RoutingKey = "agent.run.accepted.v1",
                AllowedProducers = agentProducers,
                RequiresRunIdentity = true,
                RequiresDeadline = false,
                PayloadSchema = "payloads/agent.run.accepted.schema.json",
                PayloadDtoType = typeof(AgentRunAcceptedV1),
                PayloadFields = RunEventFields(AgentFieldRule.Text("accepted_at", required: true, format: AgentFieldFormat.UtcIso))
            },
            new()
            {
                MessageType = AgentMessageTypes.RunModeSelected,
                Direction = AgentMessageDirection.AgentToBackend,
                Exchange = EventsExchange,
                RoutingKey = "agent.run.mode_selected.v1",
                AllowedProducers = agentProducers,
                RequiresRunIdentity = true,
                RequiresDeadline = false,
                PayloadSchema = "payloads/agent.run.mode_selected.schema.json",
                PayloadDtoType = typeof(AgentRunModeSelectedV1),
                PayloadFields = RunEventFields(
                    AgentFieldRule.Choice("selected_mode", required: true, "fast", "analysis", "deep_research"),
                    AgentFieldRule.Flag("requires_web_search", required: true),
                    AgentFieldRule.Text("reason", required: true, maxLength: 2000))
            },
            new()
            {
                MessageType = AgentMessageTypes.RunProgressed,
                Direction = AgentMessageDirection.AgentToBackend,
                Exchange = EventsExchange,
                RoutingKey = "agent.run.progressed.v1",
                AllowedProducers = agentProducers,
                RequiresRunIdentity = true,
                RequiresDeadline = false,
                PayloadSchema = "payloads/agent.run.progressed.schema.json",
                PayloadDtoType = typeof(AgentRunProgressedV1),
                PayloadFields = RunEventFields(
                    AgentFieldRule.Choice("kind", required: true,
                        "run_started", "mode_selected", "article_context_ready", "run_resumed",
                        "retrieval_started", "retrieval_completed", "research_started",
                        "research_round_completed", "generation_started", "generation_completed",
                        "validation_completed", "action_proposed", "tool_error", "generation_delta"),
                    AgentFieldRule.Text("message", required: true, maxLength: 2000),
                    AgentFieldRule.Map("detail", AgentFieldKind.String))
            },
            new()
            {
                MessageType = AgentMessageTypes.RunNeedsInput,
                Direction = AgentMessageDirection.AgentToBackend,
                Exchange = EventsExchange,
                RoutingKey = "agent.run.needs_input.v1",
                AllowedProducers = agentProducers,
                RequiresRunIdentity = true,
                RequiresDeadline = false,
                PayloadSchema = "payloads/agent.run.needs_input.schema.json",
                PayloadDtoType = typeof(AgentRunNeedsInputV1),
                PayloadFields = RunEventFields(
                    AgentFieldRule.List("unresolved_questions",
                        AgentFieldRule.Text("question_item", maxLength: 20000), required: true, minItems: 1),
                    UsageRule())
            },
            new()
            {
                MessageType = AgentMessageTypes.RunCompleted,
                Direction = AgentMessageDirection.AgentToBackend,
                Exchange = EventsExchange,
                RoutingKey = "agent.run.completed.v1",
                AllowedProducers = agentProducers,
                RequiresRunIdentity = true,
                RequiresDeadline = false,
                PayloadSchema = "payloads/agent.run.completed.schema.json",
                PayloadDtoType = typeof(AgentRunCompletedV1),
                PayloadFields = RunEventFields(
                    AgentFieldRule.Choice("selected_mode", required: true, "fast", "analysis", "deep_research"),
                    AgentFieldRule.Text("answer", maxLength: 200000),
                    AgentFieldRule.Text("report", maxLength: 200000),
                    AgentFieldRule.List("citations", SourceReferenceRule()),
                    AgentFieldRule.Choice("source_scope", required: true,
                        "article", "web", "article_and_web", "profile", "projects", "general"),
                    AgentFieldRule.List("unresolved_questions",
                        AgentFieldRule.Text("question_item", maxLength: 20000)),
                    UsageRule(required: true),
                    ProposalRule())
            },
            new()
            {
                MessageType = AgentMessageTypes.RunPartiallyCompleted,
                Direction = AgentMessageDirection.AgentToBackend,
                Exchange = EventsExchange,
                RoutingKey = "agent.run.partially_completed.v1",
                AllowedProducers = agentProducers,
                RequiresRunIdentity = true,
                RequiresDeadline = false,
                PayloadSchema = "payloads/agent.run.partially_completed.schema.json",
                PayloadDtoType = typeof(AgentRunPartiallyCompletedV1),
                PayloadFields = RunEventFields(
                    AgentFieldRule.Choice("selected_mode", required: true, "fast", "analysis", "deep_research"),
                    AgentFieldRule.Text("answer", maxLength: 200000),
                    AgentFieldRule.Text("report", maxLength: 200000),
                    AgentFieldRule.List("citations", SourceReferenceRule()),
                    AgentFieldRule.Choice("source_scope", required: true,
                        "article", "web", "article_and_web", "profile", "projects", "general"),
                    AgentFieldRule.List("unresolved_questions",
                        AgentFieldRule.Text("question_item", maxLength: 20000)),
                    UsageRule(required: true))
            },
            new()
            {
                MessageType = AgentMessageTypes.RunFailed,
                Direction = AgentMessageDirection.AgentToBackend,
                Exchange = EventsExchange,
                RoutingKey = "agent.run.failed.v1",
                AllowedProducers = agentProducers,
                RequiresRunIdentity = true,
                RequiresDeadline = false,
                PayloadSchema = "payloads/agent.run.failed.schema.json",
                PayloadDtoType = typeof(AgentRunFailedV1),
                PayloadFields = RunEventFields(
                    AgentFieldRule.Choice("error_code", required: true,
                        "config_error", "validation_error", "not_found", "stale_snapshot",
                        "budget_exhausted", "cancelled", "provider_error", "timeout"),
                    AgentFieldRule.Text("error_message", maxLength: 4000),
                    AgentFieldRule.Choice("selected_mode", required: false, "fast", "analysis", "deep_research"),
                    UsageRule())
            },
            new()
            {
                MessageType = AgentMessageTypes.RunCancelled,
                Direction = AgentMessageDirection.AgentToBackend,
                Exchange = EventsExchange,
                RoutingKey = "agent.run.cancelled.v1",
                AllowedProducers = agentProducers,
                RequiresRunIdentity = true,
                RequiresDeadline = false,
                PayloadSchema = "payloads/agent.run.cancelled.schema.json",
                PayloadDtoType = typeof(AgentRunCancelledV1),
                PayloadFields = RunEventFields(
                    AgentFieldRule.Text("reason", maxLength: 2000),
                    UsageRule())
            },
            new()
            {
                MessageType = AgentMessageTypes.ActionProposed,
                Direction = AgentMessageDirection.AgentToBackend,
                Exchange = EventsExchange,
                RoutingKey = "agent.action.proposed.v1",
                AllowedProducers = agentProducers,
                RequiresRunIdentity = true,
                RequiresDeadline = false,
                PayloadSchema = "payloads/agent.action.proposed.schema.json",
                PayloadDtoType = typeof(AgentActionProposedV1),
                PayloadFields = RunEventFields(
                    AgentFieldRule.Text("run_id", required: true, maxLength: 128),
                    AgentFieldRule.Text("proposal_id", required: true, maxLength: 128),
                    AgentFieldRule.Text("article_id", required: true, maxLength: 128),
                    AgentFieldRule.Integer("article_revision", required: true),
                    AgentFieldRule.Text("base_content_hash", required: true, format: AgentFieldFormat.HashHex),
                    AgentFieldRule.Text("summary", required: true, maxLength: 8000),
                    AgentFieldRule.Text("proposed_content", required: true, maxLength: 20000),
                    AgentFieldRule.Text("created_at", required: true, format: AgentFieldFormat.UtcIso))
            },
            new()
            {
                MessageType = AgentMessageTypes.ArticleContentChanged,
                Direction = AgentMessageDirection.BackendToAgent,
                Exchange = ContentExchange,
                RoutingKey = "content.article.changed.v1",
                AllowedProducers = backendProducers,
                RequiresRunIdentity = false,
                RequiresDeadline = false,
                PayloadSchema = "payloads/content.article.changed.schema.json",
                PayloadDtoType = typeof(ArticleContentChangedV1),
                PayloadFields =
                [
                    AgentFieldRule.Text("article_id", required: true, maxLength: 128),
                    AgentFieldRule.Integer("article_revision", required: true),
                    AgentFieldRule.Choice("action", required: true, "updated", "unpublished"),
                    AgentFieldRule.Text("content_hash", format: AgentFieldFormat.HashHex),
                    AgentFieldRule.Text("language", format: AgentFieldFormat.LanguageCode),
                    AgentFieldRule.Text("title", maxLength: 512)
                ]
            },
            new()
            {
                MessageType = AgentMessageTypes.SyncBatch,
                Direction = AgentMessageDirection.BackendToAgent,
                Exchange = ContentExchange,
                RoutingKey = "content.sync.batch.v1",
                AllowedProducers = backendProducers,
                RequiresRunIdentity = false,
                RequiresDeadline = false,
                PayloadSchema = "payloads/content.sync.batch.schema.json",
                PayloadDtoType = typeof(ContentSnapshotBatchV1),
                PayloadFields =
                [
                    AgentFieldRule.Text("sync_id", required: true, maxLength: 128),
                    AgentFieldRule.Integer("batch_index", required: true),
                    AgentFieldRule.Integer("total_batches", required: true, minimum: 1),
                    AgentFieldRule.List("items",
                        AgentFieldRule.Composite("item", false,
                            AgentFieldRule.Text("article_id", required: true, maxLength: 128),
                            AgentFieldRule.Integer("article_revision", required: true),
                            AgentFieldRule.Text("content_hash", required: true, format: AgentFieldFormat.HashHex)),
                        required: true,
                        minItems: 1)
                ]
            },
            new()
            {
                MessageType = AgentMessageTypes.SyncCompleted,
                Direction = AgentMessageDirection.BackendToAgent,
                Exchange = ContentExchange,
                RoutingKey = "content.sync.completed.v1",
                AllowedProducers = backendProducers,
                RequiresRunIdentity = false,
                RequiresDeadline = false,
                PayloadSchema = "payloads/content.sync.completed.schema.json",
                PayloadDtoType = typeof(ContentSnapshotCompletedV1),
                PayloadFields =
                [
                    AgentFieldRule.Text("sync_id", required: true, maxLength: 128),
                    AgentFieldRule.Integer("item_count", required: true)
                ]
            },
            new()
            {
                MessageType = AgentMessageTypes.ProfileContentChanged,
                Direction = AgentMessageDirection.BackendToAgent,
                Exchange = ContentExchange,
                RoutingKey = "content.profile.changed.v1",
                AllowedProducers = backendProducers,
                RequiresRunIdentity = false,
                RequiresDeadline = false,
                PayloadSchema = "payloads/content.profile.changed.schema.json",
                PayloadDtoType = typeof(ProfileContentChangedV1),
                PayloadFields =
                [
                    AgentFieldRule.Integer("profile_revision", required: true),
                    AgentFieldRule.Text("content_hash", required: true, format: AgentFieldFormat.HashHex),
                    AgentFieldRule.Text("context_snapshot_reference", maxLength: 512)
                ]
            },
            new()
            {
                MessageType = AgentMessageTypes.ProjectContentChanged,
                Direction = AgentMessageDirection.BackendToAgent,
                Exchange = ContentExchange,
                RoutingKey = "content.project.changed.v1",
                AllowedProducers = backendProducers,
                RequiresRunIdentity = false,
                RequiresDeadline = false,
                PayloadSchema = "payloads/content.project.changed.schema.json",
                PayloadDtoType = typeof(ProjectContentChangedV1),
                PayloadFields =
                [
                    AgentFieldRule.Text("project_id", required: true, maxLength: 128),
                    AgentFieldRule.Integer("project_revision", required: true),
                    AgentFieldRule.Text("content_hash", required: true, format: AgentFieldFormat.HashHex),
                    AgentFieldRule.Text("context_snapshot_reference", maxLength: 512)
                ]
            }
        ];
    }
}
