using System.Text.Json;
using BlogApp.Core.Application.Common.Messaging;
using BlogApp.Core.Application.Common.Options;
using BlogApp.Core.Domain.Enums;
using BlogApp.Infrastructure.Messaging;
using BlogApp.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging.Abstractions;
using Microsoft.Extensions.Options;
using Xunit;

namespace BlogApp.Presentation.Api.Tests.Messaging.Content;

/// <summary>
/// B8 makale handler akışının DB kanıtı (gerçek Postgres, scratch koşum-başına benzersiz blogdb_b8tests_<epoch-hex>):
/// içerik olayı outbox kaydı makale değişikliğiyle AYNI transaction'da kalır; görüntülenme
/// artışı revision dokunmaz; rollback'te hayalet olay oluşmaz.
/// </summary>
[Collection("agent-content-sync-b8")]
public class PostContentEventDatabaseTests : IAsyncLifetime
{
    private readonly ContentSyncDatabaseFixture _fixture;

    public PostContentEventDatabaseTests(ContentSyncDatabaseFixture fixture)
    {
        _fixture = fixture;
    }

    public Task InitializeAsync() => _fixture.ResetAsync();

    public Task DisposeAsync() => Task.CompletedTask;

    private AgentContentEventService CreateService(AppDbContext context) =>
        new(new EfOutboxWriter(context), Options.Create(new AgentMessagingSettings()), NullLogger<AgentContentEventService>.Instance);

    // Handler'ların yaptığı sıra: Observe → mutate → RecordChangeAsync → tek SaveChangesAsync.
    [Fact]
    public async Task PublishedUpdate_PersistsRevisionAndOutboxInSameCommit()
    {
        var user = await _fixture.SeedUserAsync();
        var post = await _fixture.SeedPostAsync(user.Id, "B8 SameTx Post", PostStatus.Published, contentRevision: 7);

        await using var context = _fixture.CreateContext();
        var service = CreateService(context);
        var tracked = await context.Posts.SingleAsync(p => p.Id == post.Id);
        var before = service.Observe(tracked);

        tracked.Content = "# B8 SameTx Post\n\nGuncel icerik.";
        await service.RecordChangeAsync(tracked, before);
        await context.SaveChangesAsync();

        await using var verify = _fixture.CreateContext();
        var saved = await verify.Posts.AsNoTracking().SingleAsync(p => p.Id == post.Id);
        Assert.Equal(8, saved.ContentRevision);
        var message = await verify.OutboxMessages.AsNoTracking()
            .SingleAsync(m => m.MessageType == AgentMessageTypes.ArticleContentChanged);
        Assert.Equal(AgentMessageTypeRegistry.ContentExchange, message.Exchange);
        Assert.Equal(AgentOutboxStatus.Pending, message.Status);

        var payload = JsonDocument.Parse(message.EnvelopeJson).RootElement.GetProperty("payload");
        Assert.Equal(8, payload.GetProperty("article_revision").GetInt64());
        Assert.Equal("updated", payload.GetProperty("action").GetString());
    }

    [Fact]
    public async Task TransactionWithoutCommit_PersistsNoRevisionAndNoEvent()
    {
        var user = await _fixture.SeedUserAsync();
        var post = await _fixture.SeedPostAsync(user.Id, "B8 Rollback Post", PostStatus.Published, contentRevision: 2);

        var context = _fixture.CreateContext();
        await using (context)
        await using (var transaction = await context.Database.BeginTransactionAsync())
        {
            var service = CreateService(context);
            var tracked = await context.Posts.SingleAsync(p => p.Id == post.Id);
            var before = service.Observe(tracked);
            tracked.Content = "# Farkli icerik";
            await service.RecordChangeAsync(tracked, before);
            await context.SaveChangesAsync();
            // commit YOK
        }

        await using var verify = _fixture.CreateContext();
        var saved = await verify.Posts.AsNoTracking().SingleAsync(p => p.Id == post.Id);
        Assert.Equal(2, saved.ContentRevision);
        Assert.False(await verify.OutboxMessages.AnyAsync()); // hayalet olay yok
    }

    [Fact]
    public async Task ViewCountIncrement_DoesNotTouchRevisionAndWritesNoEvent()
    {
        var user = await _fixture.SeedUserAsync();
        var post = await _fixture.SeedPostAsync(user.Id, "B8 Views Post", PostStatus.Published, contentRevision: 4);

        await using var context = _fixture.CreateContext();
        // Görüntülenme artışı handler'ın kullandığı atomik ExecuteUpdate yoludur (GetPostBySlugQuery):
        // content_revision sütununa dokunmaz, içerik olayı üretmez.
        await context.Posts
            .Where(p => p.Id == post.Id)
            .ExecuteUpdateAsync(setters => setters.SetProperty(p => p.ViewCount, p => p.ViewCount + 1));

        await using var verify = _fixture.CreateContext();
        var saved = await verify.Posts.AsNoTracking().SingleAsync(p => p.Id == post.Id);
        Assert.Equal(1, saved.ViewCount);
        Assert.Equal(4, saved.ContentRevision);
        Assert.False(await verify.OutboxMessages.AnyAsync());
    }

    [Fact]
    public async Task Unpublish_PersistsTombstoneEvent()
    {
        var user = await _fixture.SeedUserAsync();
        var post = await _fixture.SeedPostAsync(user.Id, "B8 Unpublish Post", PostStatus.Published, contentRevision: 1);

        await using var context = _fixture.CreateContext();
        var service = CreateService(context);
        var tracked = await context.Posts.SingleAsync(p => p.Id == post.Id);
        var before = service.Observe(tracked);
        tracked.Unpublish();
        await service.RecordChangeAsync(tracked, before);
        await context.SaveChangesAsync();

        await using var verify = _fixture.CreateContext();
        var message = await verify.OutboxMessages.AsNoTracking().SingleAsync();
        var payload = JsonDocument.Parse(message.EnvelopeJson).RootElement.GetProperty("payload");
        Assert.Equal("unpublished", payload.GetProperty("action").GetString());
        Assert.Equal(2, payload.GetProperty("article_revision").GetInt64());
        Assert.False(payload.TryGetProperty("content_hash", out _));
        Assert.Equal(2, (await verify.Posts.AsNoTracking().SingleAsync(p => p.Id == post.Id)).ContentRevision);
    }
}
