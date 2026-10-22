using BlogApp.Core.Application.Common.AuthorProfile;
using BlogApp.Core.Application.Common.Options;
using BlogApp.Core.Application.Features.AgentFeature.Queries.GetAgentRunEventsQuery;
using BlogApp.Core.Application.Features.AgentFeature.Queries.GetAgentRunQuery;
using BlogApp.Core.Application.Features.AgentFeature.Services;
using BlogApp.Core.Domain.Enums;
using BlogApp.Infrastructure.Services.AuthorProfile;
using BlogApp.Presentation.Api.Tests.WhoAmI;
using Microsoft.Extensions.Options;
using Xunit;

namespace BlogApp.Presentation.Api.Tests.Agent;

/// <summary>
/// Who am I sunum yüzeyleri (K6, A23/A25/A27) — B10 DB fixture'ı üzerinde: GET status konu/sürüm
/// alanlarını ve profil kaynaklarını döner; eski profil sürümüne dayanan sonuç maskelenir;
/// replay profil run'ında generation_delta gövdesini döndürmez.
/// </summary>
[Collection("agent-b10")]
public class AgentWhoAmIStatusReplayTests : IAsyncLifetime
{
    private readonly AgentB10DatabaseFixture _fixture;

    public AgentWhoAmIStatusReplayTests(AgentB10DatabaseFixture fixture) => _fixture = fixture;

    public Task InitializeAsync() => _fixture.ResetAsync();

    public Task DisposeAsync() => Task.CompletedTask;

    private static readonly IAuthorProfileSource Profile =
        new FileAuthorProfileSource(FileAuthorProfileSource.ResolveDirectory(null));

    private async Task<(Guid RunId, Guid UserId)> SeedWhoAmIRunAsync(string resultJson, BlogApp.Core.Application.Common.Messaging.AgentProfileSnapshotRef pinned)
    {
        var userId = Guid.NewGuid();
        await using var context = _fixture.CreateContext();
        var run = await AgentB10TestHost.SeedRunAsync(
            context,
            ownerKey: $"u:{userId:D}",
            status: AgentRunStatus.Completed,
            resultJson: resultJson,
            terminalAt: DateTime.UtcNow);
        run.ContextSnapshotJson = WhoAmITestData.ContextJson(2, "who_am_i", pinned);
        run.SourceScope = "profile";
        await context.SaveChangesAsync();
        return (run.Id, userId);
    }

    private GetAgentRunQueryHandler StatusHandler(Guid userId)
    {
        var context = _fixture.CreateContext();
        return new GetAgentRunQueryHandler(
            context,
            new TestCurrentUser(userId),
            new AgentResultPresentationGuard(context, Profile, Options.Create(new AgentWireV2Settings { Enabled = true })));
    }

    [Fact]
    public async Task Status_Presents_Current_Profile_Result_With_Topic_And_Citations()
    {
        var pinned = Profile.GetCurrent().ActiveSnapshot!.ToRef();
        var (runId, userId) = await SeedWhoAmIRunAsync(
            WhoAmITestData.ResultJson(snapshot: pinned, citations: [WhoAmITestData.ProfileCitation(snapshot: pinned)]), pinned);

        var result = await StatusHandler(userId).Handle(new GetAgentRunQueryRequest { RunId = runId }, CancellationToken.None);

        Assert.True(result.IsSuccess, result.Error);
        Assert.Equal("who_am_i", result.Value!.ConversationTopic);
        Assert.Equal(2, result.Value.WireVersion);
        Assert.Null(result.Value.Result!.UnavailableReason);
        Assert.Equal("profile", result.Value.Result.RunIntent);
        var citation = Assert.Single(result.Value.Result.Citations);
        Assert.Equal("/about#education", citation.Url);
        Assert.Equal("education", citation.SectionId);
    }

    [Fact]
    public async Task Status_Masks_Result_From_Previous_Profile_Revision()
    {
        var stale = WhoAmITestData.Snapshot(99, WhoAmITestData.OtherHash);
        var (runId, userId) = await SeedWhoAmIRunAsync(
            WhoAmITestData.ResultJson(snapshot: stale, citations: [WhoAmITestData.ProfileCitation(snapshot: stale)]), stale);

        var result = await StatusHandler(userId).Handle(new GetAgentRunQueryRequest { RunId = runId }, CancellationToken.None);

        Assert.True(result.IsSuccess, result.Error);
        Assert.Equal("profile_updated", result.Value!.Result!.UnavailableReason);
        Assert.Null(result.Value.Result.Answer);
        Assert.Empty(result.Value.Result.Citations);
        Assert.NotNull(result.Value.Result.UnavailableMessage);
    }

    [Fact]
    public async Task Replay_Omits_Generation_Delta_Body_For_WhoAmI_Run()
    {
        var pinned = Profile.GetCurrent().ActiveSnapshot!.ToRef();
        var (runId, userId) = await SeedWhoAmIRunAsync(WhoAmITestData.ResultJson(snapshot: pinned), pinned);
        await using (var context = _fixture.CreateContext())
        {
            await AgentB10TestHost.SeedAppliedEventAsync(context, runId, 1, "agent.run.progressed",
                payloadJson: """{"event_sequence":1,"kind":"retrieval_started","message":"Profil bölümleri aranıyor"}""",
                progressMessage: "Profil bölümleri aranıyor");
            await AgentB10TestHost.SeedAppliedEventAsync(context, runId, 2, "agent.run.progressed",
                payloadJson: """{"event_sequence":2,"kind":"generation_delta","message":"Sample Author Malat"}""",
                progressMessage: "Sample Author Malat");
        }

        await using var queryContext = _fixture.CreateContext();
        var handler = new GetAgentRunEventsQueryHandler(queryContext, new TestCurrentUser(userId));
        var result = await handler.Handle(new GetAgentRunEventsQueryRequest { RunId = runId, After = 0 }, CancellationToken.None);

        Assert.True(result.IsSuccess, result.Error);
        var status = result.Value!.Events.Single(e => e.EventSequence == 1);
        Assert.Equal("Profil bölümleri aranıyor", status.Message);
        var delta = result.Value.Events.Single(e => e.EventSequence == 2);
        Assert.Equal("generation_delta", delta.Kind);
        Assert.Null(delta.Message);
        Assert.Null(delta.Detail);
    }
}
