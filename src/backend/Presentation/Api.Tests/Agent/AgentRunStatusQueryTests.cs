using BlogApp.Core.Application.Common.Interfaces.Services;
using BlogApp.Core.Application.Features.AgentFeature.Queries.GetAgentRunEventsQuery;
using BlogApp.Core.Application.Features.AgentFeature.Queries.GetAgentRunQuery;
using BlogApp.Core.Application.Features.AgentFeature.Services;
using BlogApp.Core.Domain.Entities;
using BlogApp.Core.Domain.Enums;
using BlogApp.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;
using Xunit;
using Error = BlogApp.Core.Application.Common.Errors;

namespace BlogApp.Presentation.Api.Tests.Agent;

/// <summary>
/// B10 GET /runs/{runId} ve /runs/{runId}/events karşılığı sorgular (plan tablosu:
/// "Sahiplik kontrolüyle durum ve izin verilen sonuç" + "yetkili replay"). Kabul
/// ölçütleri: başka kullanıcının run'ına erişim ENGELİ; yenileme ve replay.
/// </summary>
[Collection("agent-b10")]
public class AgentRunStatusQueryTests : IAsyncLifetime
{
    private readonly AgentB10DatabaseFixture _fixture;

    public AgentRunStatusQueryTests(AgentB10DatabaseFixture fixture) => _fixture = fixture;

    public Task InitializeAsync() => _fixture.ResetAsync();

    public Task DisposeAsync() => Task.CompletedTask;

    private GetAgentRunQueryHandler CreateStatusHandler(Guid? userId) =>
        new(
            _fixture.CreateContext(),
            new TestCurrentUser(userId),
            new AgentResultPresentationGuard(_fixture.CreateContext()));

    private GetAgentRunEventsQueryHandler CreateEventsHandler(Guid? userId) =>
        new(_fixture.CreateContext(), new TestCurrentUser(userId));

    private async Task<BlogPost> SeedArticleAsync(bool published)
    {
        await using var context = _fixture.CreateContext();
        var author = new User
        {
            UserName = $"b10-author-{Guid.NewGuid():N}",
            Email = $"b10-{Guid.NewGuid():N}@example.com",
            PasswordHash = "test-only-not-a-secret",
        };
        context.Users.Add(author);
        await context.SaveChangesAsync();

        var post = new BlogPost
        {
            Title = "B10 makale",
            Slug = $"b10-makale-{Guid.NewGuid():N}",
            Content = "# B10\n\nİçerik",
            Status = published ? PostStatus.Published : PostStatus.Draft,
            AuthorId = author.Id,
        };
        if (published)
        {
            post.Publish();
        }

        context.Posts.Add(post);
        await context.SaveChangesAsync();
        return post;
    }

    // ------------------------------------------------------------- sahiplik

    [Fact]
    public async Task Run_WithoutAnyIdentity_IsUnauthorized()
    {
        var run = await AgentB10TestHost.SeedRunAsync(_fixture.CreateContext(), ownerKey: "u:someone");

        var result = await CreateStatusHandler(userId: null).Handle(
            new GetAgentRunQueryRequest { RunId = run.Id }, CancellationToken.None);

        Assert.True(result.IsFailure);
        Assert.Equal(Error.ErrorCategory.Unauthorized, result.ErrorDetail!.Category);
    }

    [Fact]
    public async Task Run_OfAnotherUser_IsForbidden()
    {
        var run = await AgentB10TestHost.SeedRunAsync(_fixture.CreateContext(), ownerKey: "u:another-b10");

        var result = await CreateStatusHandler(Guid.NewGuid()).Handle(
            new GetAgentRunQueryRequest { RunId = run.Id }, CancellationToken.None);

        Assert.True(result.IsFailure);
        Assert.Equal(Error.ErrorCategory.Forbidden, result.ErrorDetail!.Category);
    }

    [Fact]
    public async Task Run_OfGuestOwner_WithMatchingGuestSession_IsAllowed()
    {
        var run = await AgentB10TestHost.SeedRunAsync(_fixture.CreateContext(), ownerKey: "g:guest-b10");

        var result = await CreateStatusHandler(userId: null).Handle(
            new GetAgentRunQueryRequest { RunId = run.Id, GuestSessionId = "guest-b10" },
            CancellationToken.None);

        Assert.True(result.IsSuccess);
        Assert.Equal(run.Id, result.Value!.RunId);
        Assert.Equal("Accepted", result.Value.Status);
    }

    [Fact]
    public async Task Run_UnknownRun_IsNotFound()
    {
        var result = await CreateStatusHandler(Guid.NewGuid()).Handle(
            new GetAgentRunQueryRequest { RunId = Guid.NewGuid() }, CancellationToken.None);

        Assert.True(result.IsFailure);
        Assert.Equal(Error.ErrorCategory.NotFound, result.ErrorDetail!.Category);
    }

    // ------------------------------------------------- durum alanları (ayrı gösterim)

    [Fact]
    public async Task Run_AcceptedWithoutEvents_HasNoSelectedModeAndNoResult()
    {
        var userId = Guid.NewGuid();
        var run = await AgentB10TestHost.SeedRunAsync(
            _fixture.CreateContext(), ownerKey: $"u:{userId:D}");

        var result = await CreateStatusHandler(userId).Handle(
            new GetAgentRunQueryRequest { RunId = run.Id }, CancellationToken.None);

        Assert.True(result.IsSuccess);
        Assert.Equal("Accepted", result.Value!.Status);     // kabul durumu
        Assert.Null(result.Value.SelectedMode);              // başlama: mod seçilmedi
        Assert.Null(result.Value.Result);                    // tamamlanma: sonuç yok
        Assert.Null(result.Value.TerminalAt);
    }

    // ------------------------------------------------- izin verilen sonuç + maskeleme

    [Fact]
    public async Task Run_CompletedResult_IsReturnedWithCitations()
    {
        var userId = Guid.NewGuid();
        var article = await SeedArticleAsync(published: true);
        var resultJson = $$"""
            {"event_sequence":7,"selected_mode":"fast","source_scope":"article_only","answer":"Cevap","citations":[{"kind":"article","article_id":"{{article.Id:D}}","article_revision":1,"chunk_index":2,"title":"B10 makale","source_id":"article:{{article.Id:D}}#giris"}]}
            """;
        var run = await AgentB10TestHost.SeedRunAsync(
            _fixture.CreateContext(),
            ownerKey: $"u:{userId:D}",
            status: AgentRunStatus.Completed,
            articleId: article.Id,
            resultJson: resultJson,
            selectedMode: "fast",
            terminalAt: DateTime.UtcNow);

        var result = await CreateStatusHandler(userId).Handle(
            new GetAgentRunQueryRequest { RunId = run.Id }, CancellationToken.None);

        Assert.True(result.IsSuccess);
        Assert.Equal("Completed", result.Value!.Status);
        Assert.NotNull(result.Value.Result);
        Assert.Equal("Cevap", result.Value.Result!.Answer);
        var citation = Assert.Single(result.Value.Result.Citations);
        Assert.Equal("article", citation.Kind);
        Assert.Equal(article.Id, citation.ArticleId);
        Assert.Equal("fast", result.Value.Result.SelectedMode);
        Assert.Null(result.Value.Result.UnavailableReason);
    }

    [Fact]
    public async Task Run_ArticleUnpublished_ResultIsMaskedWithReason()
    {
        var userId = Guid.NewGuid();
        var article = await SeedArticleAsync(published: false); // yayın erişimi yok (B8)
        var run = await AgentB10TestHost.SeedRunAsync(
            _fixture.CreateContext(),
            ownerKey: $"u:{userId:D}",
            status: AgentRunStatus.Completed,
            articleId: article.Id,
            resultJson: """{"answer":"gizli","citations":[]}""",
            terminalAt: DateTime.UtcNow);

        var result = await CreateStatusHandler(userId).Handle(
            new GetAgentRunQueryRequest { RunId = run.Id }, CancellationToken.None);

        Assert.True(result.IsSuccess);
        Assert.NotNull(result.Value!.Result);
        Assert.Null(result.Value.Result!.Answer); // içerik DÖNMEZ
        Assert.NotNull(result.Value.Result.UnavailableReason);
    }

    // ------------------------------------------------- replay (GET events)

    [Fact]
    public async Task Events_ReplayReturnsAppliedEventsInOrder()
    {
        var userId = Guid.NewGuid();
        var context = _fixture.CreateContext();
        var run = await AgentB10TestHost.SeedRunAsync(context, ownerKey: $"u:{userId:D}");
        await AgentB10TestHost.SeedAppliedEventAsync(context, run.Id, 1, "agent.run.accepted");
        await AgentB10TestHost.SeedAppliedEventAsync(context, run.Id, 2, "agent.run.mode_selected");
        await AgentB10TestHost.SeedAppliedEventAsync(context, run.Id, 3, "agent.run.progressed");

        var result = await CreateEventsHandler(userId).Handle(
            new GetAgentRunEventsQueryRequest { RunId = run.Id }, CancellationToken.None);

        Assert.True(result.IsSuccess);
        Assert.Equal(3, result.Value!.Events.Count);
        Assert.Equal([1L, 2L, 3L], result.Value.Events.Select(e => e.EventSequence).ToArray());
        Assert.Equal("Accepted", result.Value.RunStatus);
    }

    [Fact]
    public async Task Events_AfterCursor_ReturnsOnlyNewerEvents_YenilemeReplay()
    {
        var userId = Guid.NewGuid();
        var context = _fixture.CreateContext();
        var run = await AgentB10TestHost.SeedRunAsync(context, ownerKey: $"u:{userId:D}");
        await AgentB10TestHost.SeedAppliedEventAsync(context, run.Id, 1, "agent.run.accepted");
        await AgentB10TestHost.SeedAppliedEventAsync(context, run.Id, 2, "agent.run.progressed");

        var first = await CreateEventsHandler(userId).Handle(
            new GetAgentRunEventsQueryRequest { RunId = run.Id }, CancellationToken.None);
        Assert.True(first.IsSuccess);
        Assert.Equal(2, first.Value!.Events.Count); // ilk yoklama tüm geçmişi getirir

        // Yenileme sonrası istemci after=1 ile kaldığı yerden sürer: yalnız yeni olay.
        var resumed = await CreateEventsHandler(userId).Handle(
            new GetAgentRunEventsQueryRequest { RunId = run.Id, After = 1 }, CancellationToken.None);

        Assert.True(resumed.IsSuccess);
        var events = resumed.Value!.Events;
        Assert.Single(events);
        Assert.Equal(2, events[0].EventSequence);
    }

    [Fact]
    public async Task Events_StaleRows_AreNotReplayed()
    {
        var userId = Guid.NewGuid();
        var context = _fixture.CreateContext();
        var run = await AgentB10TestHost.SeedRunAsync(context, ownerKey: $"u:{userId:D}");
        await AgentB10TestHost.SeedAppliedEventAsync(context, run.Id, 1, "agent.run.accepted");
        context.AgentEventInboxes.Add(new AgentEventInbox
        {
            ConsumerName = "backend-agent-events",
            MessageId = Guid.NewGuid(),
            MessageType = "agent.run.progressed",
            RunId = run.Id,
            EventSequence = 0, // sıra gerilemesi → stale
            Status = "stale",
            CreatedAt = DateTime.UtcNow,
        });
        await context.SaveChangesAsync();

        var result = await CreateEventsHandler(userId).Handle(
            new GetAgentRunEventsQueryRequest { RunId = run.Id }, CancellationToken.None);

        Assert.True(result.IsSuccess);
        Assert.Single(result.Value!.Events);
    }

    [Fact]
    public async Task Events_OfAnotherUser_IsForbidden()
    {
        var run = await AgentB10TestHost.SeedRunAsync(_fixture.CreateContext(), ownerKey: "u:another-b10");

        var result = await CreateEventsHandler(Guid.NewGuid()).Handle(
            new GetAgentRunEventsQueryRequest { RunId = run.Id }, CancellationToken.None);

        Assert.True(result.IsFailure);
        Assert.Equal(Error.ErrorCategory.Forbidden, result.ErrorDetail!.Category);
    }
}
