using System.Text.Json;
using BlogApp.Core.Application.Common.Interfaces.Data;
using BlogApp.Core.Application.Common.Interfaces.Messaging;
using BlogApp.Core.Application.Common.Messaging;
using BlogApp.Core.Application.Common.Options;
using BlogApp.Core.Application.Features.AgentFeature.Services;
using BlogApp.Core.Domain.Entities;
using BlogApp.Core.Domain.Enums;
using BlogApp.Infrastructure.Messaging;
using BlogApp.Infrastructure.Persistence;
using BlogApp.Infrastructure.Persistence.Repositories;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging.Abstractions;
using Microsoft.Extensions.Options;
using Xunit;

namespace BlogApp.Presentation.Api.Tests.Messaging.Content;

/// <summary>
/// B8 backend'in başlattığı ilk senkron testleri (gerçek Postgres): batch sınırı,
/// completed item_count, değişiklik watermark'ı ve taslak/arşiv dışlaması.
/// </summary>
[Collection("agent-content-sync-b8")]
public class ContentSnapshotSyncServiceTests : IAsyncLifetime
{
    private readonly ContentSyncDatabaseFixture _fixture;

    public ContentSnapshotSyncServiceTests(ContentSyncDatabaseFixture fixture)
    {
        _fixture = fixture;
    }

    public Task InitializeAsync() => _fixture.ResetAsync();

    public Task DisposeAsync() => Task.CompletedTask;

    private ContentSnapshotSyncService CreateService(int batchSize)
    {
        var context = _fixture.CreateContext();
        return new ContentSnapshotSyncService(
            context,
            new UnitOfWork(context),
            new EfOutboxWriter(context),
            Options.Create(new AgentContentSyncSettings { BatchSize = batchSize }),
            Options.Create(new AgentMessagingSettings()),
            NullLogger<ContentSnapshotSyncService>.Instance);
    }

    [Fact]
    public async Task Sync_ProducesBatchesAndCompletedWithWatermark()
    {
        var user = await _fixture.SeedUserAsync();
        await _fixture.SeedPostAsync(user.Id, "Sync One", PostStatus.Published, contentRevision: 3);
        await _fixture.SeedPostAsync(user.Id, "Sync Two", PostStatus.Published, contentRevision: 5);
        await _fixture.SeedPostAsync(user.Id, "Sync Three", PostStatus.Published, contentRevision: 1);
        await _fixture.SeedPostAsync(user.Id, "Sync Draft", PostStatus.Draft);
        await _fixture.SeedPostAsync(user.Id, "Sync Archived", PostStatus.Archived);

        var summary = await CreateService(batchSize: 2).RunSyncAsync();

        Assert.Equal(3, summary.ItemCount);
        Assert.Equal(2, summary.TotalBatches);
        Assert.Equal(5, summary.RevisionWatermark); // snapshot anındaki en yüksek revision

        await using var verify = _fixture.CreateContext();
        var batchMessages = await verify.OutboxMessages.AsNoTracking()
            .Where(m => m.MessageType == AgentMessageTypes.SyncBatch)
            .ToListAsync();
        Assert.Equal(2, batchMessages.Count);

        // W5 flaky kök nedeni: OutboxMessage.Id GUID'dir; Id'ye göre sıralama
        // fiziksel yazım sırasını TEMSİL ETMEZ → batch 0/1 karışır (kapıda tek
        // seferlik FAIL). Sıra semantik alan olan batch_index'ten okunur.
        var batches = batchMessages
            .Select(m => (Message: m, Payload: JsonDocument.Parse(m.EnvelopeJson).RootElement.GetProperty("payload")))
            .OrderBy(x => x.Payload.GetProperty("batch_index").GetInt64())
            .ToList();

        var first = batches[0].Payload;
        Assert.Equal(0, first.GetProperty("batch_index").GetInt64());
        Assert.Equal(2, first.GetProperty("total_batches").GetInt64());
        Assert.Equal(2, first.GetProperty("items").GetArrayLength());
        var second = batches[1].Payload;
        Assert.Equal(1, second.GetProperty("batch_index").GetInt64());
        Assert.Equal(1, second.GetProperty("items").GetArrayLength());

        // Tüm kalem referansları (article_id, revision, hash) üçlüsü taşınır (K7).
        foreach (var batch in batches)
        {
            var result = new AgentContractValidator().Validate(batch.Message.EnvelopeJson);
            Assert.True(result.IsValid, result.Error?.Message);
        }

        var completed = await verify.OutboxMessages.AsNoTracking()
            .SingleAsync(m => m.MessageType == AgentMessageTypes.SyncCompleted);
        var completedPayload = JsonDocument.Parse(completed.EnvelopeJson).RootElement.GetProperty("payload");
        Assert.Equal(3, completedPayload.GetProperty("item_count").GetInt64());

        var syncRecord = await verify.AgentContentSyncs.AsNoTracking().SingleAsync();
        Assert.Equal(AgentContentSyncStatus.Completed, syncRecord.Status);
        Assert.Equal(3, syncRecord.ItemCount);
        Assert.Equal(2, syncRecord.TotalBatches);
        Assert.Equal(5, syncRecord.RevisionWatermark);
        Assert.NotNull(syncRecord.CompletedAt);
        Assert.Equal(summary.SyncId, syncRecord.SyncId);

        // Taslak/arşiv olayla taşınmaz: hiçbir batch kalem hash'i taslak içerikten üretilmez.
        var draft = await verify.Posts.AsNoTracking().SingleAsync(p => p.Status == PostStatus.Draft);
        var allItems = batches
            .SelectMany(b => b.Payload.GetProperty("items").EnumerateArray())
            .ToList();
        Assert.All(allItems, item => Assert.NotEqual(draft.Id.ToString("D"), item.GetProperty("article_id").GetString()));
    }

    [Fact]
    public async Task Sync_WithNoPublishedPosts_WritesOnlyCompleted()
    {
        var user = await _fixture.SeedUserAsync();
        await _fixture.SeedPostAsync(user.Id, "Only Draft", PostStatus.Draft);

        var summary = await CreateService(batchSize: 50).RunSyncAsync();

        Assert.Equal(0, summary.ItemCount);
        Assert.Equal(0, summary.TotalBatches);

        await using var verify = _fixture.CreateContext();
        Assert.False(await verify.OutboxMessages.AnyAsync(m => m.MessageType == AgentMessageTypes.SyncBatch));
        var completed = await verify.OutboxMessages.AsNoTracking()
            .SingleAsync(m => m.MessageType == AgentMessageTypes.SyncCompleted);
        Assert.Equal(0, JsonDocument.Parse(completed.EnvelopeJson).RootElement
            .GetProperty("payload").GetProperty("item_count").GetInt64());
    }

    [Fact]
    public async Task Sync_ItemsCarryCurrentRevisionsSoLiveChangesDominateLater()
    {
        // "Senkron sürerken olan değişiklikler kaybolmaz": snapshot referansı rev N'yi taşır;
        // sonrasındaki canlı değişiklik N+1 olayını üretir — consumer monotonlukla birleştirir.
        var user = await _fixture.SeedUserAsync();
        var post = await _fixture.SeedPostAsync(user.Id, "Sync Race", PostStatus.Published, contentRevision: 2);

        var summary = await CreateService(batchSize: 10).RunSyncAsync();

        // Snapshot SONRASI canlı değişiklik (handler akışının aynısı):
        await using var context = _fixture.CreateContext();
        var service = new AgentContentEventService(
            new EfOutboxWriter(context),
            Options.Create(new AgentMessagingSettings()),
            NullLogger<AgentContentEventService>.Instance);
        var tracked = await context.Posts.SingleAsync(p => p.Id == post.Id);
        var before = service.Observe(tracked);
        tracked.Content = "# Sync Race\n\nDegisti.";
        await service.RecordChangeAsync(tracked, before);
        await context.SaveChangesAsync();

        await using var verify = _fixture.CreateContext();
        var batch = await verify.OutboxMessages.AsNoTracking()
            .SingleAsync(m => m.MessageType == AgentMessageTypes.SyncBatch);
        var item = JsonDocument.Parse(batch.EnvelopeJson).RootElement.GetProperty("payload")
            .GetProperty("items")[0];
        Assert.Equal(2, item.GetProperty("article_revision").GetInt64()); // snapshot anı
        var live = await verify.OutboxMessages.AsNoTracking()
            .SingleAsync(m => m.MessageType == AgentMessageTypes.ArticleContentChanged);
        var livePayload = JsonDocument.Parse(live.EnvelopeJson).RootElement.GetProperty("payload");
        Assert.Equal(3, livePayload.GetProperty("article_revision").GetInt64()); // canlı olay daha yeni
        Assert.Equal(summary.SyncId, (await verify.AgentContentSyncs.AsNoTracking().SingleAsync()).SyncId);
    }
}

/// <summary>B8 sunum öncesi güncellik denetimi testleri (plan B8: "içerik kullanılamıyor" durumu).</summary>
[Collection("agent-content-sync-b8")]
public class AgentResultPresentationGuardTests : IAsyncLifetime
{
    private readonly ContentSyncDatabaseFixture _fixture;

    public AgentResultPresentationGuardTests(ContentSyncDatabaseFixture fixture)
    {
        _fixture = fixture;
    }

    public Task InitializeAsync() => _fixture.ResetAsync();

    public Task DisposeAsync() => Task.CompletedTask;

    private static string ResultJson(params (Guid articleId, string kind)[] citations)
    {
        var payload = new
        {
            selected_mode = "fast",
            source_scope = "article",
            citations = citations.Select(c => new { kind = c.kind, article_id = c.articleId.ToString("D") }).ToArray(),
        };
        return JsonSerializer.Serialize(payload);
    }

    private async Task<AgentRun> SeedRunAsync(Guid? articleId, string resultJson)
    {
        await using var context = _fixture.CreateContext();
        var run = new AgentRun
        {
            Id = Guid.NewGuid(),
            ConversationId = Guid.NewGuid(),
            TurnSequence = 1,
            OwnerKey = "u:presentation-guard",
            IdempotencyKey = Guid.NewGuid().ToString("D"),
            IdempotencyPayloadHash = "hash-not-used",
            Status = AgentRunStatus.Completed,
            Question = "Soru",
            Language = "tr",
            ModePreference = "fast",
            BudgetProfile = "standard",
            ArticleId = articleId,
            ResultJson = resultJson,
            ContextSnapshotJson = "{}", // jsonb kolon: boş string geçersiz JSON'dur
            ContextSnapshotReference = "agent-run/turn/1",
            DeadlineAt = DateTime.UtcNow.AddMinutes(5),
            AcceptedAt = DateTime.UtcNow,
        };
        context.AgentRuns.Add(run);
        await context.SaveChangesAsync();
        return run;
    }

    [Fact]
    public async Task ResultCitingPublishedArticle_IsPresentable()
    {
        var user = await _fixture.SeedUserAsync();
        var article = await _fixture.SeedPostAsync(user.Id, "Guard Published", PostStatus.Published);
        var run = await SeedRunAsync(article.Id, ResultJson((article.Id, "article")));

        var guard = new AgentResultPresentationGuard(_fixture.CreateContext());
        var decision = await guard.CheckAsync(run.Id);

        Assert.True(decision.IsPresentable);
        Assert.Empty(decision.UnavailableArticleIds);
        Assert.Null(decision.UnavailableReason);
    }

    [Fact]
    public async Task ResultCitingUnpublishedArticle_IsContentUnavailable()
    {
        var user = await _fixture.SeedUserAsync();
        var published = await _fixture.SeedPostAsync(user.Id, "Guard Ok", PostStatus.Published);
        var unpublished = await _fixture.SeedPostAsync(user.Id, "Guard Unpublished", PostStatus.Draft);
        var run = await SeedRunAsync(null, ResultJson(
            (published.Id, "article"),
            (unpublished.Id, "article")));

        var guard = new AgentResultPresentationGuard(_fixture.CreateContext());
        var decision = await guard.CheckAsync(run.Id);

        Assert.False(decision.IsPresentable);
        Assert.Contains(unpublished.Id, decision.UnavailableArticleIds);
        Assert.Contains(published.Id, decision.AvailableArticleIds);
        Assert.NotNull(decision.UnavailableReason);
    }

    [Fact]
    public async Task SoftDeletedArticle_IsUnavailableEvenWithQueryFilter()
    {
        var user = await _fixture.SeedUserAsync();
        var deleted = await _fixture.SeedPostAsync(user.Id, "Guard Deleted", PostStatus.Published);
        await using (var context = _fixture.CreateContext())
        {
            var tracked = await context.Posts.SingleAsync(p => p.Id == deleted.Id);
            tracked.IsDeleted = true;
            await context.SaveChangesAsync();
        }

        var run = await SeedRunAsync(null, ResultJson((deleted.Id, "article")));
        var guard = new AgentResultPresentationGuard(_fixture.CreateContext());
        var decision = await guard.CheckAsync(run.Id);

        // IgnoreQueryFilters olmadan silinmiş makale sorgulanamaz ve sonuç yanlışlıkla sunulurdu.
        Assert.False(decision.IsPresentable);
        Assert.Contains(deleted.Id, decision.UnavailableArticleIds);
    }

    [Fact]
    public async Task ContextArticleOfRun_IsAlsoChecked()
    {
        var user = await _fixture.SeedUserAsync();
        var archived = await _fixture.SeedPostAsync(user.Id, "Guard Context", PostStatus.Published);
        await using (var context = _fixture.CreateContext())
        {
            var tracked = await context.Posts.SingleAsync(p => p.Id == archived.Id);
            tracked.Archive();
            await context.SaveChangesAsync();
        }

        var run = await SeedRunAsync(archived.Id, "{}");
        var guard = new AgentResultPresentationGuard(_fixture.CreateContext());
        var decision = await guard.CheckAsync(run.Id);

        Assert.False(decision.IsPresentable);
        Assert.Contains(archived.Id, decision.UnavailableArticleIds);
    }

    [Fact]
    public async Task ResultWithoutArticleReferences_IsPresentable()
    {
        var run = await SeedRunAsync(null, "{}");

        var guard = new AgentResultPresentationGuard(_fixture.CreateContext());
        var decision = await guard.CheckAsync(run.Id);

        Assert.True(decision.IsPresentable);
        Assert.Empty(decision.AvailableArticleIds);
    }

    [Fact]
    public async Task UnknownRunId_IsNotPresentable()
    {
        var guard = new AgentResultPresentationGuard(_fixture.CreateContext());
        var decision = await guard.CheckAsync(Guid.NewGuid());

        Assert.False(decision.IsPresentable);
    }

    [Fact]
    public async Task NonObjectResultJson_StillChecksContextArticle()
    {
        // ResultJson jsonb kolonundadır: DB'de her zaman geçerli JSON'dur. Nesne olmayan
        // (ör. dizi) bir snapshot'ta citations aranamaz; bağlam makalesi yine denetlenir.
        var user = await _fixture.SeedUserAsync();
        var published = await _fixture.SeedPostAsync(user.Id, "Guard Corrupt", PostStatus.Published);
        var run = await SeedRunAsync(published.Id, "[]");

        var guard = new AgentResultPresentationGuard(_fixture.CreateContext());
        var decision = await guard.CheckAsync(run.Id);

        Assert.True(decision.IsPresentable);
        Assert.Contains(published.Id, decision.AvailableArticleIds);
    }
}
