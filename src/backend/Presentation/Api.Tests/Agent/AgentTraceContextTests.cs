using System.Diagnostics;
using System.Text.Json;
using BlogApp.Core.Application.Common.Messaging;
using Xunit;

namespace BlogApp.Presentation.Api.Tests.Agent;

public sealed class AgentTraceContextTests
{
    public static TheoryData<string, int> Envelopes() => new()
    {
        { "execute", 1 }, { "execute", 2 },
        { "cancel", 1 }, { "cancel", 2 },
        { "resume", 1 }, { "resume", 2 },
        { "collaboration_resume", 1 }, { "collaboration_resume", 2 },
        { "action_result", 1 }, { "action_result", 2 },
        { "article", 1 }, { "sync_batch", 1 }, { "sync_completed", 1 },
        { "profile", 1 }, { "project", 1 },
    };

    [Theory]
    [MemberData(nameof(Envelopes))]
    public void CurrentW3cActivityReachesEveryCommandAndContentEnvelope(string kind, int version)
    {
        using var activity = new Activity("request").SetIdFormat(ActivityIdFormat.W3C).Start();
        var json = Compose(kind, version);
        using var document = JsonDocument.Parse(json);
        Assert.True(document.RootElement.TryGetProperty("trace_context", out var parent),
            "The production envelope factory lost the request's trace parent.");
        Assert.Equal(activity.Id, parent.GetString());
        var result = new AgentContractValidator().Validate(json);
        Assert.True(result.IsValid, result.Error?.ToString());
    }

    [Fact]
    public void HierarchicalActivityIsOmittedInsteadOfBreakingTheWireContract()
    {
        using var activity = new Activity("legacy-request").SetIdFormat(ActivityIdFormat.Hierarchical).Start();
        using var document = JsonDocument.Parse(Compose("execute", 1));
        Assert.False(document.RootElement.TryGetProperty("trace_context", out _));
    }

    [Fact]
    public void OutboxRedeliveryKeepsTheOriginalParentAndMessageIdentity()
    {
        using var request = new Activity("request").SetIdFormat(ActivityIdFormat.W3C).Start();
        var json = Compose("execute", 1);
        using var relay = new Activity("relay").SetIdFormat(ActivityIdFormat.W3C).Start();
        using var original = JsonDocument.Parse(json);
        using var replay = JsonDocument.Parse(AgentCommandEnvelopeComposer.WithDeliveryAttempt(json, 3));
        Assert.Equal(request.Id, replay.RootElement.GetProperty("trace_context").GetString());
        Assert.Equal(original.RootElement.GetProperty("message_id").GetString(),
            replay.RootElement.GetProperty("message_id").GetString());
    }

    private static string Compose(string kind, int version)
    {
        var run = Guid.NewGuid();
        var conversation = Guid.NewGuid();
        var correlation = Guid.NewGuid().ToString("D");
        var now = DateTimeOffset.UtcNow;
        const string hash = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
        return kind switch
        {
            "execute" => AgentCommandEnvelopeComposer.ComposeExecutionRequested(run, conversation, correlation,
                now, now.AddMinutes(5), "backend-net", "u:1", "Question", "en", "fast", "standard", null, null,
                schemaVersion: version, conversationTopic: version == 1 ? null : "auto").EnvelopeJson,
            "cancel" => AgentControlEnvelopeComposer.ComposeCancellationRequested(run, conversation, correlation,
                now, "backend-net", null, version).EnvelopeJson,
            "resume" => AgentResumeEnvelopeComposer.ComposeResumeRequested(run, conversation, correlation,
                now, "backend-net", "checkpoint/1", "u:1", version).EnvelopeJson,
            "collaboration_resume" => AgentCollaborationEnvelopeComposer.ComposeResumeRequested(run, conversation,
                correlation, now, "backend-net", "checkpoint/1", "u:1", version).EnvelopeJson,
            "action_result" => AgentCollaborationEnvelopeComposer.ComposeActionResult(run, conversation, correlation,
                now, "backend-net", Guid.NewGuid(), "accepted", null, 1, now, schemaVersion: version).EnvelopeJson,
            "article" => AgentContentEventComposer.ComposeArticleChanged(Guid.NewGuid(), 1, "updated", hash,
                "en", "Approved title", "backend-net").EnvelopeJson,
            "sync_batch" => AgentContentEventComposer.ComposeSyncBatch(Guid.NewGuid().ToString("D"), 0, 1,
                [(Guid.NewGuid(), 1, hash)], "backend-net").EnvelopeJson,
            "sync_completed" => AgentContentEventComposer.ComposeSyncCompleted(Guid.NewGuid().ToString("D"),
                1, "backend-net").EnvelopeJson,
            "profile" => AgentContentEventComposer.ComposeProfileChanged(1, hash, "backend-net").EnvelopeJson,
            "project" => AgentContentEventComposer.ComposeProjectChanged(Guid.NewGuid(), 1, hash, "backend-net").EnvelopeJson,
            _ => throw new ArgumentOutOfRangeException(nameof(kind)),
        };
    }
}
