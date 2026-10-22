using System.Text.Json;
using System.Text.Json.Nodes;
using BlogApp.Core.Application.Common.AuthorProfile;
using BlogApp.Core.Application.Common.Messaging;
using BlogApp.Core.Application.Common.Options;
using BlogApp.Core.Application.Features.AgentFeature.Services;
using BlogApp.Core.Domain.Enums;
using BlogApp.Infrastructure.Messaging;
using BlogApp.Infrastructure.Persistence;
using BlogApp.Infrastructure.Persistence.Repositories;
using BlogApp.Infrastructure.Services.AuthorProfile;
using BlogApp.Presentation.Api.Tests.WhoAmI;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging.Abstractions;
using Microsoft.Extensions.Options;
using Xunit;

namespace BlogApp.Presentation.Api.Tests.Messaging.Projection;

/// <summary>
/// v2 projection (K4/K6) broker'sız DB davranışı: mode_selected etkin kapsamı run'a yazılır;
/// pinlenmiş snapshot/konu/sürüm ihlali olay reddi + güvenli Failed kapanışı; who_am_i
/// generation_delta push edilmez ve gövdesiz saklanır; doğrulanmış profil sonucu bildirimde sunulur.
/// </summary>
[Collection("agent-event-projection")]
public sealed class AgentV2ProjectionHandlerTests
{
    private readonly AgentEventProjectionFixture _fixture;

    public AgentV2ProjectionHandlerTests(AgentEventProjectionFixture fixture)
    {
        _fixture = fixture;
    }

    private static readonly IAuthorProfileSource Profile =
        new FileAuthorProfileSource(FileAuthorProfileSource.ResolveDirectory(null));

    private static AgentProfileSnapshotRef Pinned => Profile.GetCurrent().ActiveSnapshot!.ToRef();

    private async Task<Guid> SeedV2RunAsync(string topic)
    {
        await using var context = _fixture.CreateContext();
        var run = await AgentRunSeeder.SeedAsync(context);
        run.ContextSnapshotJson = WhoAmITestData.ContextJson(2, topic, Pinned);
        await context.SaveChangesAsync();
        return run.Id;
    }

    private static AgentRunEventProjectionHandler Handler(AppDbContext context) =>
        new(
            new UnitOfWork(context),
            context,
            new EfAgentCollaborationStore(context),
            new AgentResultPresentationGuard(context, Profile, Options.Create(new AgentWireV2Settings { Enabled = true })),
            NullLogger<AgentRunEventProjectionHandler>.Instance);

    private static AgentRunEventProjectionEvent Event(
        Guid runId,
        string messageType,
        JsonObject payload,
        int schemaVersion = 2,
        bool isTerminal = false,
        AgentRunStatus? terminalStatus = null,
        string? selectedMode = null,
        string? sourceScope = null,
        string? runIntent = null,
        AgentProfileSnapshotRef? snapshot = null,
        string? progressKind = null,
        string? progressMessage = null) =>
        new(
            AgentRunEventProjectionHandler.ConsumerName,
            new AgentEnvelope
            {
                MessageId = Guid.NewGuid().ToString("D"),
                MessageType = messageType,
                SchemaVersion = schemaVersion,
                RunId = runId.ToString("D"),
                ConversationId = Guid.NewGuid().ToString("D"),
                CorrelationId = Guid.NewGuid().ToString("D"),
                OccurredAt = "2026-10-22T09:00:00Z",
                Producer = "agent-py",
                Payload = JsonSerializer.SerializeToElement(payload),
            },
            PayloadJson: payload.ToJsonString(),
            EventSequence: payload["event_sequence"]!.AsValue().TryGetValue<long>(out var sequence) ? sequence : payload["event_sequence"]!.GetValue<int>(),
            IsTerminal: isTerminal,
            TerminalStatus: terminalStatus,
            SelectedMode: selectedMode,
            ProgressMessage: progressMessage,
            SourceScope: sourceScope,
            RunIntent: runIntent,
            ProfileSnapshot: snapshot,
            ProgressKind: progressKind);

    [Fact]
    public async Task ModeSelected_V2_Persists_Effective_Scope()
    {
        await _fixture.ResetAsync();
        var runId = await SeedV2RunAsync("auto");
        await using var context = _fixture.CreateContext();

        var result = await Handler(context).ApplyAsync(Event(runId, AgentMessageTypes.RunModeSelected,
            new JsonObject { ["event_sequence"] = 1 }, selectedMode: "fast", sourceScope: "profile",
            runIntent: "profile", snapshot: Pinned));

        Assert.Equal(AgentEventDecision.Apply, result.Decision);
        var run = await context.AgentRuns.AsNoTracking().SingleAsync(r => r.Id == runId);
        Assert.Equal("profile", run.SourceScope);
        Assert.Equal("fast", run.SelectedMode);
        Assert.Equal(AgentRunStatus.Accepted, run.Status);
    }

    [Fact]
    public async Task Completed_With_Snapshot_Different_From_Pinned_Is_Rejected_And_Run_Fails_Safely()
    {
        await _fixture.ResetAsync();
        var runId = await SeedV2RunAsync("who_am_i");
        await using var context = _fixture.CreateContext();
        var other = WhoAmITestData.Snapshot(99, WhoAmITestData.OtherHash);
        var payload = JsonNode.Parse(WhoAmITestData.ResultJson(snapshot: other))!.AsObject();
        payload["event_sequence"] = 3;

        var result = await Handler(context).ApplyAsync(Event(runId, AgentMessageTypes.RunCompleted, payload,
            isTerminal: true, terminalStatus: AgentRunStatus.Completed, sourceScope: "profile",
            runIntent: "profile", snapshot: other));

        Assert.Equal(AgentEventDecision.Rejected, result.Decision);
        Assert.Equal("rejected", result.InboxStatus);
        Assert.Equal("Failed", result.Notification!.Status);
        Assert.Null(result.Notification.ResultJson);

        var run = await context.AgentRuns.AsNoTracking().SingleAsync(r => r.Id == runId);
        Assert.Equal(AgentRunStatus.Failed, run.Status);
        Assert.DoesNotContain("Malatya", run.ResultJson);
        var inbox = await context.AgentEventInboxes.AsNoTracking().SingleAsync();
        Assert.Equal("rejected", inbox.Status);
        Assert.Null(inbox.PayloadJson);
    }

    [Fact]
    public async Task V1_Event_For_V2_Run_Is_Rejected()
    {
        await _fixture.ResetAsync();
        var runId = await SeedV2RunAsync("auto");
        await using var context = _fixture.CreateContext();

        var result = await Handler(context).ApplyAsync(Event(runId, AgentMessageTypes.RunProgressed,
            new JsonObject { ["event_sequence"] = 1, ["kind"] = "run_started", ["message"] = "başladı" },
            schemaVersion: 1, progressKind: "run_started", progressMessage: "başladı"));

        Assert.Equal(AgentEventDecision.Rejected, result.Decision);
    }

    [Fact]
    public async Task WhoAmI_Generation_Delta_Is_Not_Pushed_Or_Stored_With_Body()
    {
        await _fixture.ResetAsync();
        var runId = await SeedV2RunAsync("who_am_i");
        await using var context = _fixture.CreateContext();

        var result = await Handler(context).ApplyAsync(Event(runId, AgentMessageTypes.RunProgressed,
            new JsonObject { ["event_sequence"] = 2, ["kind"] = "generation_delta", ["message"] = "Berkay Kaplan Malat" },
            progressKind: "generation_delta", progressMessage: "Berkay Kaplan Malat"));

        Assert.Equal(AgentEventDecision.Apply, result.Decision);
        Assert.Null(result.Notification);
        var inbox = await context.AgentEventInboxes.AsNoTracking().SingleAsync();
        Assert.Equal("applied", inbox.Status);
        Assert.Null(inbox.ProgressMessage);
        Assert.DoesNotContain("Malat", inbox.PayloadJson);
    }

    [Fact]
    public async Task Verified_Profile_Completion_Is_Presented_In_Notification()
    {
        await _fixture.ResetAsync();
        var runId = await SeedV2RunAsync("who_am_i");
        await using var context = _fixture.CreateContext();
        var payload = JsonNode.Parse(WhoAmITestData.ResultJson(snapshot: Pinned, citations: [WhoAmITestData.ProfileCitation(snapshot: Pinned)]))!.AsObject();
        payload["event_sequence"] = 4;

        var result = await Handler(context).ApplyAsync(Event(runId, AgentMessageTypes.RunCompleted, payload,
            isTerminal: true, terminalStatus: AgentRunStatus.Completed, sourceScope: "profile",
            runIntent: "profile", snapshot: Pinned));

        Assert.Equal(AgentEventDecision.Apply, result.Decision);
        Assert.NotNull(result.Notification!.ResultJson);
        var run = await context.AgentRuns.AsNoTracking().SingleAsync(r => r.Id == runId);
        Assert.Equal(AgentRunStatus.Completed, run.Status);
        Assert.Equal("profile", run.SourceScope);
    }

    [Fact]
    public async Task Terminal_Fills_SelectedMode_Only_When_ModeSelected_Was_Not_Applied()
    {
        await _fixture.ResetAsync();
        var runId = await SeedV2RunAsync("who_am_i");
        await using var context = _fixture.CreateContext();
        var payload = JsonNode.Parse(WhoAmITestData.ResultJson(snapshot: Pinned, citations: [WhoAmITestData.ProfileCitation(snapshot: Pinned)]))!.AsObject();
        payload["event_sequence"] = 4;

        // mode_selected sırasız teslimde düşmüş: terminal olay kesinleşmiş modu yazar.
        var result = await Handler(context).ApplyAsync(Event(runId, AgentMessageTypes.RunCompleted, payload,
            isTerminal: true, terminalStatus: AgentRunStatus.Completed, selectedMode: "fast", sourceScope: "profile",
            runIntent: "profile", snapshot: Pinned));

        Assert.Equal(AgentEventDecision.Apply, result.Decision);
        var run = await context.AgentRuns.AsNoTracking().SingleAsync(r => r.Id == runId);
        Assert.Equal("fast", run.SelectedMode);
    }
}
