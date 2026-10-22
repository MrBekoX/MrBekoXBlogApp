using System.Text.Json;
using BlogApp.Core.Application.Common.AuthorProfile;
using BlogApp.Core.Application.Common.Interfaces.Services;
using BlogApp.Core.Application.Common.Messaging;
using BlogApp.Core.Application.Common.Options;
using BlogApp.Core.Application.Features.AgentFeature.Commands.AcceptAgentRunCommand;
using BlogApp.Core.Application.Features.AgentFeature.Services;
using BlogApp.Core.Domain.Enums;
using BlogApp.Infrastructure.Messaging;
using BlogApp.Infrastructure.Persistence.Repositories;
using BlogApp.Infrastructure.Services.AuthorProfile;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging.Abstractions;
using Microsoft.Extensions.Options;
using Xunit;
using Error = BlogApp.Core.Application.Common.Errors;

namespace BlogApp.Presentation.Api.Tests.Messaging.Outbox;

/// <summary>
/// Who am I kabul senaryoları (K4/K6) — gerçek Postgres (B3 izole scratch DB) üzerinde:
/// v2 kapalıyken who_am_i 503, v2 açıkken pinlenmiş profil + .v2 routing + v2 zarf, AUTO'da profil
/// kapasitesi kaydı, konu kilidi, konuyu kapsayan idempotency (A28) ve v2 konuşma geçmişi.
/// Wire seçici sahte (broker hazırlığı ayrı testte); profil kaynağı build çıktısındaki canonical kopya.
/// </summary>
[Collection("agent-rabbitmq-outbox")]
public class AgentWhoAmIAcceptanceTests : IAsyncLifetime
{
    private readonly AgentOutboxDatabaseFixture _fixture;

    public AgentWhoAmIAcceptanceTests(AgentOutboxDatabaseFixture fixture)
    {
        _fixture = fixture;
    }

    public Task InitializeAsync() => _fixture.ResetAsync();

    public Task DisposeAsync() => Task.CompletedTask;

    private sealed class FixedWireSelector(int version) : IAgentWireVersionSelector
    {
        public Task<int> SelectAsync(CancellationToken cancellationToken = default) => Task.FromResult(version);
    }

    private sealed class FixedProfileSource(AuthorProfileState state) : IAuthorProfileSource
    {
        public AuthorProfileState GetCurrent() => state;
    }

    private static IAuthorProfileSource PackagedProfile() =>
        new FileAuthorProfileSource(FileAuthorProfileSource.ResolveDirectory(null));

    private AcceptAgentRunCommandHandler CreateHandler(Guid? userId, int wireVersion, IAuthorProfileSource? profile = null)
    {
        var context = _fixture.CreateContext();
        profile ??= PackagedProfile();
        var guard = new AgentResultPresentationGuard(
            context, profile, Options.Create(new AgentWireV2Settings { Enabled = wireVersion == 2 }));
        return new AcceptAgentRunCommandHandler(
            new UnitOfWork(context),
            context,
            new TestCurrentUser(userId),
            new EfOutboxWriter(context),
            Options.Create(new AgentAcceptanceSettings { AllowGuestRuns = true, MaxActiveRunsPerOwner = 10 }),
            Options.Create(new AgentMessagingSettings()),
            NullLogger<AcceptAgentRunCommandHandler>.Instance,
            new FixedWireSelector(wireVersion),
            profile,
            new AgentConversationHistoryComposer(context, guard));
    }

    private static AcceptAgentRunCommandRequest Request(string topic, string key = "who-key-1", Guid? conversationId = null) => new()
    {
        Question = "Sample Author hangi üniversitede okudu?",
        Language = "tr",
        ModePreference = "auto",
        BudgetProfile = "standard",
        IdempotencyKey = key,
        ConversationTopic = topic,
        ConversationId = conversationId,
        GuestSessionId = "guest-whoami",
    };

    [Fact]
    public async Task WhoAmI_When_Wire_V2_Unavailable_Is_503_And_Writes_Nothing()
    {
        var result = await CreateHandler(userId: null, wireVersion: 1).Handle(Request("who_am_i"), CancellationToken.None);

        Assert.True(result.IsFailure);
        Assert.Equal(Error.ErrorCategory.Unavailable, result.ErrorDetail!.Category);
        Assert.Equal("capability_unavailable", result.ErrorDetail.Code);
        await using var context = _fixture.CreateContext();
        Assert.False(await context.AgentRuns.AnyAsync());
        Assert.False(await context.OutboxMessages.AnyAsync());
    }

    [Fact]
    public async Task WhoAmI_On_V2_Pins_Profile_And_Routes_To_V2_Queue()
    {
        var result = await CreateHandler(userId: null, wireVersion: 2).Handle(Request("who_am_i"), CancellationToken.None);

        Assert.True(result.IsSuccess, result.ErrorDetail?.ToString());
        Assert.Equal("who_am_i", result.Value!.ConversationTopic);
        Assert.Equal(2, result.Value.WireVersion);

        await using var context = _fixture.CreateContext();
        var run = await context.AgentRuns.AsNoTracking().SingleAsync();
        var wire = AgentRunWireContext.Parse(run.ContextSnapshotJson);
        Assert.Equal(2, wire.WireVersion);
        Assert.True(wire.IsWhoAmI);
        Assert.True(PackagedProfile().GetCurrent().ActiveSnapshot!.Matches(wire.PinnedProfile));
        Assert.Null(run.ArticleId);

        var outbox = await context.OutboxMessages.AsNoTracking().SingleAsync();
        Assert.Equal("agent.execute.requested.v2", outbox.RoutingKey);
        Assert.True(new AgentContractValidator().TryValidateAs<AgentExecutionRequestedV2>(
            outbox.EnvelopeJson, out var envelope, out var payload, out var error), error?.ToString());
        Assert.Equal(2, envelope!.SchemaVersion);
        Assert.Equal("who_am_i", payload!.ConversationTopic);
        Assert.True(payload.ProfileSnapshot!.SameAs(wire.PinnedProfile));
    }

    [Fact]
    public async Task WhoAmI_With_Unavailable_Profile_Is_503()
    {
        var withdrawn = new FixedProfileSource(AuthorProfileState.Unavailable(AuthorProfileAvailability.NotPublic, "geri çekildi"));

        var result = await CreateHandler(null, 2, withdrawn).Handle(Request("who_am_i"), CancellationToken.None);

        Assert.Equal(Error.ErrorCategory.Unavailable, result.ErrorDetail!.Category);
        await using var context = _fixture.CreateContext();
        Assert.False(await context.AgentRuns.AnyAsync());
    }

    [Fact]
    public async Task Auto_On_V2_Without_Profile_Records_Unavailable_Capability_And_Proceeds()
    {
        var missing = new FixedProfileSource(AuthorProfileState.Unavailable(AuthorProfileAvailability.Missing, "yok"));

        var result = await CreateHandler(null, 2, missing).Handle(Request("auto"), CancellationToken.None);

        Assert.True(result.IsSuccess, result.ErrorDetail?.ToString());
        await using var context = _fixture.CreateContext();
        var run = await context.AgentRuns.AsNoTracking().SingleAsync();
        var wire = AgentRunWireContext.Parse(run.ContextSnapshotJson);
        Assert.Equal("unavailable", wire.ProfileCapability);
        Assert.Null(wire.PinnedProfile);
        var outbox = await context.OutboxMessages.AsNoTracking().SingleAsync();
        using var document = JsonDocument.Parse(outbox.EnvelopeJson);
        Assert.False(document.RootElement.GetProperty("payload").TryGetProperty("profile_snapshot", out _));
    }

    [Fact]
    public async Task Auto_On_V1_Is_Unchanged_Legacy_Flow()
    {
        var result = await CreateHandler(null, 1).Handle(Request("auto"), CancellationToken.None);

        Assert.True(result.IsSuccess, result.ErrorDetail?.ToString());
        await using var context = _fixture.CreateContext();
        var outbox = await context.OutboxMessages.AsNoTracking().SingleAsync();
        Assert.Equal("agent.execute.requested.v1", outbox.RoutingKey);
        Assert.True(new AgentContractValidator().TryValidateAs<AgentExecutionRequestedV1>(outbox.EnvelopeJson, out _, out _, out var error), error?.ToString());
        var wire = AgentRunWireContext.Parse((await context.AgentRuns.AsNoTracking().SingleAsync()).ContextSnapshotJson);
        Assert.Equal(1, wire.WireVersion);
        Assert.Equal("auto", wire.ConversationTopic);
    }

    [Fact]
    public async Task Same_Idempotency_Key_With_Different_Topic_Conflicts()
    {
        var handler = CreateHandler(null, 2);
        Assert.True((await handler.Handle(Request("auto", "same-key"), CancellationToken.None)).IsSuccess);

        var second = await CreateHandler(null, 2).Handle(Request("who_am_i", "same-key"), CancellationToken.None);

        Assert.Equal(Error.ErrorCategory.Conflict, second.ErrorDetail!.Category);
    }

    [Fact]
    public async Task Conversation_Topic_Cannot_Change()
    {
        var first = await CreateHandler(null, 2).Handle(Request("who_am_i", "k-1"), CancellationToken.None);
        Assert.True(first.IsSuccess, first.ErrorDetail?.ToString());

        var second = await CreateHandler(null, 2).Handle(
            Request("auto", "k-2", first.Value!.ConversationId), CancellationToken.None);

        Assert.Equal(Error.ErrorCategory.Validation, second.ErrorDetail!.Category);
        Assert.Contains("ConversationTopic", second.ErrorDetail.FieldErrors!.Keys);
    }

    [Fact]
    public async Task V2_Follow_Up_Carries_Presentable_History_Only()
    {
        var first = await CreateHandler(null, 2).Handle(Request("who_am_i", "h-1"), CancellationToken.None);
        Assert.True(first.IsSuccess, first.ErrorDetail?.ToString());
        var pinned = PackagedProfile().GetCurrent().ActiveSnapshot!.ToRef();

        // İlk turu terminal profil sonucuyla tamamla (projection'ın yazacağı şekil).
        await using (var context = _fixture.CreateContext())
        {
            var run = await context.AgentRuns.SingleAsync(r => r.Id == first.Value!.RunId);
            run.Status = AgentRunStatus.Completed;
            run.TerminalAt = DateTime.UtcNow;
            run.SourceScope = "profile";
            run.ResultJson = ProfileResult(pinned, "Demo University, Bilgisayar Mühendisliği (2000–2004).");
            await context.SaveChangesAsync();
        }

        var second = await CreateHandler(null, 2).Handle(
            Request("who_am_i", "h-2", first.Value!.ConversationId) with { Question = "Peki eğitmenlik?" }, CancellationToken.None);
        Assert.True(second.IsSuccess, second.ErrorDetail?.ToString());

        await using var verify = _fixture.CreateContext();
        var outbox = await verify.OutboxMessages.AsNoTracking().SingleAsync(m => m.RunId == second.Value!.RunId);
        Assert.True(new AgentContractValidator().TryValidateAs<AgentExecutionRequestedV2>(outbox.EnvelopeJson, out _, out var payload, out var error), error?.ToString());
        var history = payload!.ConversationHistory!;
        Assert.Equal(["user", "assistant"], history.Select(t => t.Role));
        Assert.Equal("Sample Author hangi üniversitede okudu?", history[0].Content);
        Assert.Contains("Demo", history[1].Content);
    }

    [Fact]
    public async Task V2_History_Skips_Turns_From_A_Stale_Profile_Revision()
    {
        var first = await CreateHandler(null, 2).Handle(Request("who_am_i", "s-1"), CancellationToken.None);
        Assert.True(first.IsSuccess, first.ErrorDetail?.ToString());

        await using (var context = _fixture.CreateContext())
        {
            var run = await context.AgentRuns.SingleAsync(r => r.Id == first.Value!.RunId);
            // Pinlenmiş sürümden farklı (eski) snapshot'a dayanan sonuç → sunum denetimi maskeler.
            run.Status = AgentRunStatus.Completed;
            run.TerminalAt = DateTime.UtcNow;
            run.ResultJson = ProfileResult(new AgentProfileSnapshotRef
            {
                ProfileId = "sample-author",
                Revision = 99,
                ContentHash = new string('e', 64),
            }, "eski profil cevabı");
            await context.SaveChangesAsync();
        }

        var second = await CreateHandler(null, 2).Handle(
            Request("who_am_i", "s-2", first.Value!.ConversationId) with { Question = "Peki staj?" }, CancellationToken.None);
        Assert.True(second.IsSuccess, second.ErrorDetail?.ToString());

        await using var verify = _fixture.CreateContext();
        var outbox = await verify.OutboxMessages.AsNoTracking().SingleAsync(m => m.RunId == second.Value!.RunId);
        using var document = JsonDocument.Parse(outbox.EnvelopeJson);
        Assert.False(document.RootElement.GetProperty("payload").TryGetProperty("conversation_history", out _));
    }

    private static string ProfileResult(AgentProfileSnapshotRef snapshot, string answer) =>
        JsonSerializer.Serialize(new Dictionary<string, object?>
        {
            ["event_sequence"] = 5,
            ["selected_mode"] = "fast",
            ["answer"] = answer,
            ["citations"] = Array.Empty<object>(),
            ["source_scope"] = "profile",
            ["run_intent"] = "profile",
            ["usage"] = new Dictionary<string, object?> { ["run_id"] = "r", ["recorded_at"] = "2026-10-22T09:00:00Z" },
            ["profile_snapshot"] = new Dictionary<string, object?>
            {
                ["profile_id"] = snapshot.ProfileId,
                ["revision"] = snapshot.Revision,
                ["content_hash"] = snapshot.ContentHash,
            },
        });

    private sealed class TestCurrentUser(Guid? userId) : ICurrentUserService
    {
        public Guid? UserId => userId;
        public string? UserName => userId is null ? null : "test-user";
        public string? Email => null;
        public string? CorrelationId => null;
        public bool IsAuthenticated => userId is not null;
        public bool IsInRole(string role) => false;
    }
}
