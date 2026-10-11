using System.Text.Json.Nodes;
using BlogApp.Core.Application.Common.Messaging;
using Xunit;

namespace BlogApp.Presentation.Api.Tests.Messaging;

/// <summary>B1 kural uygulaması: çapraz kurallar, AMQP header tutarlılığı, monoton event_sequence.</summary>
public sealed class AgentMessagingRuleTests
{
    private const string RunId = "aaaaaaa1-0000-4000-8000-000000000001";
    private const string ConvId = "bbbbbbb1-0000-4000-8000-000000000002";
    private const string CorrId = "ccccccc1-0000-4000-8000-000000000003";
    private const string Hash = "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08";

    private readonly AgentContractValidator _validator = new();

    [Fact]
    public void Article_Reference_Trio_Is_All_Or_None()
    {
        // article_id eksikken revision + hash verildi: üçlü kuralı ihlali.
        var error = ValidateExecuteRequested();

        Assert.NotNull(error);
        Assert.Equal(AgentContractErrorCategory.WrongType, error!.Category);
    }

    [Fact]
    public void Accepted_Action_Requires_Applied_Revision()
    {
        var json = CommandEnvelope("agent.action.result", /*lang=json,strict*/ """
        {"proposal_id":"prop-1","outcome":"accepted","validated_at":"2026-10-11T10:00:00Z"}
        """);

        var result = _validator.Validate(json);

        Assert.Equal(AgentContractErrorCategory.MissingField, result.Error!.Category);
        Assert.Contains("applied_article_revision", result.Error.Field);
    }

    [Fact]
    public void Web_Flag_Is_Only_Valid_For_Deep_Research()
    {
        var json = RunEventEnvelope("agent.run.mode_selected", /*lang=json,strict*/ """
        {"event_sequence":2,"selected_mode":"fast","requires_web_search":true,"reason":"kisa soru"}
        """);

        var result = _validator.Validate(json);

        Assert.Equal(AgentContractErrorCategory.WrongType, result.Error!.Category);
    }

    [Fact]
    public void Usage_Run_Id_Must_Match_Envelope_Run_Id()
    {
        var json = RunEventEnvelope("agent.run.failed", /*lang=json,strict*/ """
        {"event_sequence":4,"error_code":"provider_error","usage":{"run_id":"99999999-9999-4999-8999-999999999999","recorded_at":"2026-10-11T09:04:30Z"}}
        """);

        var result = _validator.Validate(json);

        Assert.Equal(AgentContractErrorCategory.WrongType, result.Error!.Category);
        Assert.Contains("usage.run_id", result.Error.Field);
    }

    [Fact]
    public void Action_Proposed_Run_Id_Must_Match_Envelope()
    {
        var json = RunEventEnvelope("agent.action.proposed", /*lang=json,strict*/ $$"""
        {"event_sequence":6,"run_id":"99999999-9999-4999-8999-999999999999","proposal_id":"prop-1","article_id":"my-blog-post","article_revision":7,"base_content_hash":"{{Hash}}","summary":"ozet","proposed_content":"icerik","created_at":"2026-10-11T09:04:20Z"}
        """);

        var result = _validator.Validate(json);

        Assert.Equal(AgentContractErrorCategory.WrongType, result.Error!.Category);
        Assert.Contains("payload.run_id", result.Error.Field);
    }

    [Fact]
    public void Batch_Index_Must_Be_Lower_Than_Total_Batches()
    {
        var json = ContentEnvelope("content.sync.batch", /*lang=json,strict*/ $$"""
        {"sync_id":"sync-1","batch_index":3,"total_batches":3,"items":[{"article_id":"post-a","article_revision":1,"content_hash":"{{Hash}}"}]}
        """);

        var result = _validator.Validate(json);

        Assert.Equal(AgentContractErrorCategory.WrongType, result.Error!.Category);
    }

    [Fact]
    public void Updated_Article_Requires_Hash_And_Unpublished_Forbids_It()
    {
        var missingHash = ContentEnvelope("content.article.changed", /*lang=json,strict*/ """
        {"article_id":"post-a","article_revision":8,"action":"updated"}
        """);
        var forbiddenHash = ContentEnvelope("content.article.changed", /*lang=json,strict*/ $$"""
        {"article_id":"post-a","article_revision":8,"action":"unpublished","content_hash":"{{Hash}}"}
        """);

        Assert.Equal(AgentContractErrorCategory.MissingField, _validator.Validate(missingHash).Error!.Category);
        Assert.Equal(AgentContractErrorCategory.WrongType, _validator.Validate(forbiddenHash).Error!.Category);
    }

    [Fact]
    public void Explicit_Null_Fields_Are_Rejected()
    {
        var json = CommandEnvelope("agent.cancel.requested", /*lang=json,strict*/ """
        {"reason":null}
        """);

        var result = _validator.Validate(json);

        Assert.Equal(AgentContractErrorCategory.WrongType, result.Error!.Category);
        Assert.Contains("reason", result.Error.Field);
    }

    [Fact]
    public void Amqp_Properties_Are_Consistent_With_Envelope()
    {
        var json = File.ReadAllText(Path.Combine(ContractPaths.FixturesDirectory, "valid", "agent.run.progressed.json"));
        var result = _validator.Validate(json);

        Assert.True(result.IsValid, result.Error?.ToString());
        var amqp = AgentAmqpProperties.FromEnvelope(result.Envelope!);

        Assert.Equal(result.Envelope!.MessageId, amqp.MessageId);
        Assert.Equal(result.Envelope.CorrelationId, amqp.CorrelationId);
        Assert.Equal("application/json", amqp.ContentType);
        Assert.Equal("agent.run.progressed", amqp.Type);
    }

    [Fact]
    public void Event_Sequence_Guard_Rejects_Equal_And_Lower_Sequence()
    {
        var guard = new AgentEventSequenceGuard();

        Assert.True(guard.TryAccept(RunId, 1, out _));
        Assert.True(guard.TryAccept(RunId, 5, out _));
        Assert.False(guard.TryAccept(RunId, 5, out var equalError));
        Assert.False(guard.TryAccept(RunId, 4, out var lowerError));
        Assert.True(guard.TryAccept(RunId, 6, out _));

        Assert.Contains("gerilemesi", equalError!.Message);
        Assert.Contains("gerilemesi", lowerError!.Message);
    }

    [Fact]
    public void Different_Runs_Track_Sequence_Independently()
    {
        var guard = new AgentEventSequenceGuard();

        Assert.True(guard.TryAccept(RunId, 3, out _));
        Assert.True(guard.TryAccept(ConvId, 1, out _));
    }

    [Fact]
    public void Delivery_Attempt_Is_Separate_From_Execution_Attempt()
    {
        // Aynı message_id yeniden yayınlandığında delivery_attempt artar; payload'taki
        // execution_attempt aynı kalır (plan satır 237: ayrı alanlar).
        var json = RunEventEnvelope("agent.run.progressed", /*lang=json,strict*/ """
        {"event_sequence":3,"execution_attempt":1,"fencing_token":"lease-0003","kind":"retrieval_started","message":"baglam hazirlaniyor"}
        """, deliveryAttempt: 4);

        var result = _validator.Validate(json);

        Assert.True(result.IsValid, result.Error?.ToString());
        Assert.Equal(4, result.Envelope!.DeliveryAttempt);
        Assert.Equal(1, result.PayloadNode!["execution_attempt"]!.GetValue<long>());
    }

    private AgentContractError? ValidateExecuteRequested()
    {
        var json = CommandEnvelope("agent.execute.requested", $$"""
        {"user_ref":"user-42","question":"soru","language":"tr","mode_preference":"fast","budget_profile":"fast-default","article_revision":7,"article_content_hash":"{{Hash}}"}
        """, deadline: "2026-10-11T09:05:00Z");

        return _validator.Validate(json).Error;
    }

    private string CommandEnvelope(string messageType, string payload, string? deadline = null) =>
        Envelope(messageType, payload, producer: "backend-net", deadline: deadline, withRunIdentity: true);

    private string RunEventEnvelope(string messageType, string payload, string producer = "agent-py", int deliveryAttempt = 0) =>
        Envelope(messageType, payload, producer: producer, deadline: null, withRunIdentity: true, deliveryAttempt: deliveryAttempt);

    private string ContentEnvelope(string messageType, string payload) =>
        Envelope(messageType, payload, producer: "backend-net", deadline: null, withRunIdentity: false);

    private static string Envelope(string messageType, string payload, string producer, string? deadline, bool withRunIdentity, int deliveryAttempt = 0)
    {
        var runIdentity = withRunIdentity
            ? $@"""run_id"":""{RunId}"",""conversation_id"":""{ConvId}"","
            : string.Empty;
        var deadlineField = deadline is null ? string.Empty : $@"""deadline_at"":""{deadline}"",";
        return /*lang=json,strict*/ $$"""
        {
          "message_id":"77777777-7777-4777-8777-777777777777",
          "message_type":"{{messageType}}",
          "schema_version":1,
          {{runIdentity}}"correlation_id":"{{CorrId}}",
          "occurred_at":"2026-10-11T09:00:00Z",
          {{deadlineField}}"producer":"{{producer}}",
          "delivery_attempt":{{deliveryAttempt}},
          "payload":{{payload}}
        }
        """;
    }
}
