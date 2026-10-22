using System.Text.Json;
using BlogApp.Core.Application.Common.Messaging;
using BlogApp.Core.Application.Features.AgentFeature.Queries.GetAgentRunEventsQuery;
using BlogApp.Core.Application.Features.AgentFeature.Services;
using Xunit;

namespace BlogApp.Presentation.Api.Tests.WhoAmI;

/// <summary>
/// Projection'ın olay ↔ run bağlamı kuralları (K4/K6): sürüm eşitliği, who_am_i'de profile niyeti,
/// pinlenmiş snapshot eşitliği; profil run'ında generation_delta bastırma kararları (push + replay).
/// </summary>
public sealed class AgentRunEventWireRulesTests
{
    private static readonly AgentRunWireContext V1 = AgentRunWireContext.Legacy;
    private static readonly AgentRunWireContext WhoAmI =
        AgentRunWireContext.Parse(WhoAmITestData.ContextJson(2, "who_am_i", WhoAmITestData.Snapshot()));
    private static readonly AgentRunWireContext AutoPinned =
        AgentRunWireContext.Parse(WhoAmITestData.ContextJson(2, "auto", WhoAmITestData.Snapshot()));
    private static readonly AgentRunWireContext AutoUnpinned =
        AgentRunWireContext.Parse(WhoAmITestData.ContextJson(2, "auto", null, "unavailable"));

    [Theory]
    [InlineData(2, 1)]
    [InlineData(1, 2)]
    public void Event_Version_Must_Equal_Run_Wire_Version(int eventVersion, int runVersion)
    {
        var context = runVersion == 1 ? V1 : AutoPinned;

        var violation = AgentRunEventWireRules.Verify(context, eventVersion, AgentMessageTypes.RunProgressed, null, null);

        Assert.NotNull(violation);
    }

    [Fact]
    public void V1_Events_For_V1_Runs_Pass_Unchanged()
    {
        Assert.Null(AgentRunEventWireRules.Verify(V1, 1, AgentMessageTypes.RunCompleted, null, null));
    }

    [Fact]
    public void WhoAmI_Requires_Profile_Intent()
    {
        Assert.NotNull(AgentRunEventWireRules.Verify(WhoAmI, 2, AgentMessageTypes.RunModeSelected, "general", null));
        Assert.NotNull(AgentRunEventWireRules.Verify(WhoAmI, 2, AgentMessageTypes.RunCompleted, "article_qa", null));
        Assert.Null(AgentRunEventWireRules.Verify(WhoAmI, 2, AgentMessageTypes.RunCompleted, "profile", WhoAmITestData.Snapshot()));
        // failed: niyet yönlendirme öncesi bilinmeyebilir (ör. config_error).
        Assert.Null(AgentRunEventWireRules.Verify(WhoAmI, 2, AgentMessageTypes.RunFailed, null, null));
    }

    [Fact]
    public void WhoAmI_Cannot_Suspend_Or_Propose_Actions()
    {
        Assert.NotNull(AgentRunEventWireRules.Verify(WhoAmI, 2, AgentMessageTypes.RunNeedsInput, null, null));
        Assert.NotNull(AgentRunEventWireRules.Verify(WhoAmI, 2, AgentMessageTypes.ActionProposed, null, null));
        // AUTO run'larda iş birliği akışı korunur.
        Assert.Null(AgentRunEventWireRules.Verify(AutoPinned, 2, AgentMessageTypes.RunNeedsInput, null, null));
        Assert.Null(AgentRunEventWireRules.Verify(AutoPinned, 2, AgentMessageTypes.ActionProposed, null, null));
    }

    [Fact]
    public void Profile_Snapshot_Must_Equal_Pinned()
    {
        var other = WhoAmITestData.Snapshot(2, WhoAmITestData.OtherHash);

        Assert.NotNull(AgentRunEventWireRules.Verify(WhoAmI, 2, AgentMessageTypes.RunCompleted, "profile", other));
        Assert.NotNull(AgentRunEventWireRules.Verify(AutoPinned, 2, AgentMessageTypes.RunModeSelected, "profile", other));
        Assert.Null(AgentRunEventWireRules.Verify(AutoPinned, 2, AgentMessageTypes.RunModeSelected, "profile", WhoAmITestData.Snapshot()));
    }

    [Fact]
    public void Unpinned_Run_Cannot_Receive_Profile_Snapshot()
    {
        Assert.NotNull(AgentRunEventWireRules.Verify(AutoUnpinned, 2, AgentMessageTypes.RunCompleted, "profile", WhoAmITestData.Snapshot()));
        Assert.NotNull(AgentRunEventWireRules.Verify(AutoUnpinned, 2, AgentMessageTypes.RunCompleted, "profile", null));
        // Profil kapasitesi yokken AUTO→PROFILE config_error ile biter (snapshot'sız failed geçerli).
        Assert.Null(AgentRunEventWireRules.Verify(AutoUnpinned, 2, AgentMessageTypes.RunFailed, "profile", null));
        Assert.Null(AgentRunEventWireRules.Verify(AutoUnpinned, 2, AgentMessageTypes.RunCompleted, "article_qa", null));
    }

    [Fact]
    public void Rejection_Result_Carries_No_Content()
    {
        using var document = JsonDocument.Parse(AgentRunEventProjectionHandler.RejectionResultJson(AgentMessageTypes.RunCompleted));
        var root = document.RootElement;

        Assert.Equal("validation_error", root.GetProperty("error_code").GetString());
        Assert.False(root.TryGetProperty("answer", out _));
        Assert.False(root.TryGetProperty("citations", out _));
    }

    [Fact]
    public void Generation_Delta_Is_Suppressed_For_Profile_Runs_Only()
    {
        var delta = ProgressEvent("generation_delta");
        var status = ProgressEvent("retrieval_started");

        Assert.True(AgentRunEventProjectionHandler.IsSuppressedDelta(delta, WhoAmI, runSourceScope: null));
        Assert.True(AgentRunEventProjectionHandler.IsSuppressedDelta(delta, AutoPinned, runSourceScope: "profile")); // AUTO→PROFILE
        Assert.False(AgentRunEventProjectionHandler.IsSuppressedDelta(delta, AutoPinned, runSourceScope: "article"));
        Assert.False(AgentRunEventProjectionHandler.IsSuppressedDelta(delta, V1, runSourceScope: null));
        Assert.False(AgentRunEventProjectionHandler.IsSuppressedDelta(status, WhoAmI, runSourceScope: "profile"));
    }

    [Fact]
    public void Replay_Suppresses_Delta_Bodies_For_Profile_Runs()
    {
        Assert.True(GetAgentRunEventsQueryHandler.ShouldSuppressDeltaBodies(WhoAmITestData.ContextJson(2, "who_am_i", WhoAmITestData.Snapshot()), null));
        Assert.True(GetAgentRunEventsQueryHandler.ShouldSuppressDeltaBodies(WhoAmITestData.ContextJson(2, "auto"), "profile"));
        Assert.False(GetAgentRunEventsQueryHandler.ShouldSuppressDeltaBodies(WhoAmITestData.ContextJson(2, "auto"), "article"));
        Assert.False(GetAgentRunEventsQueryHandler.ShouldSuppressDeltaBodies("""{"question":"x"}""", null));
    }

    private static AgentRunEventProjectionEvent ProgressEvent(string kind) =>
        new(
            AgentRunEventProjectionHandler.ConsumerName,
            new AgentEnvelope
            {
                MessageId = Guid.NewGuid().ToString("D"),
                MessageType = AgentMessageTypes.RunProgressed,
                SchemaVersion = 2,
                RunId = Guid.NewGuid().ToString("D"),
                ConversationId = Guid.NewGuid().ToString("D"),
                CorrelationId = Guid.NewGuid().ToString("D"),
                OccurredAt = "2026-10-22T09:00:00Z",
                Producer = "agent-py",
                Payload = JsonSerializer.SerializeToElement(new { event_sequence = 3, kind, message = "x" }),
            },
            PayloadJson: "{}",
            EventSequence: 3,
            IsTerminal: false,
            ProgressMessage: "x",
            ProgressKind: kind);
}
