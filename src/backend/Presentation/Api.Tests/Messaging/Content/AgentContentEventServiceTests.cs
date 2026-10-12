using BlogApp.Core.Application.Common.Interfaces.Messaging;
using BlogApp.Core.Application.Common.Messaging;
using BlogApp.Core.Application.Common.Options;
using BlogApp.Core.Domain.Entities;
using BlogApp.Core.Domain.Enums;
using Microsoft.Extensions.Logging.Abstractions;
using Microsoft.Extensions.Options;
using Xunit;

namespace BlogApp.Presentation.Api.Tests.Messaging.Content;

/// <summary>
/// B8 karar tablosu birim testleri (DB'siz): revision artışı yalnız yayımlanmış içerik
/// anlarında olur; taslak taşınmaz; kaldırma tombstone'u content_hash TAŞIMAZ (B1 şeması).
/// </summary>
public class AgentContentEventServiceTests
{
    private static AgentContentEventService CreateService(RecordingOutboxWriter writer) =>
        new(writer, Options.Create(new AgentMessagingSettings()), NullLogger<AgentContentEventService>.Instance);

    private static BlogPost PublishedPost(string content = "# Baslik\n\nIcerik.", long revision = 0) =>
        new()
        {
            Id = Guid.NewGuid(),
            Title = "Baslik",
            Slug = "baslik",
            Content = content,
            Status = PostStatus.Published,
            IsDeleted = false,
            ContentRevision = revision,
        };

    [Fact]
    public async Task DraftLifecycle_ProducesNoEventAndNoRevision()
    {
        var writer = new RecordingOutboxWriter();
        var service = CreateService(writer);
        var post = PublishedPost();
        post.Status = PostStatus.Draft;
        var before = service.Observe(post);

        post.Content = "# Yeni\n\nTaslak icerigi.";
        await service.RecordChangeAsync(post, before);

        Assert.Equal(0, post.ContentRevision);
        Assert.Empty(writer.Messages);
    }

    [Fact]
    public async Task Publish_IncrementsRevisionAndWritesUpdatedEventWithHash()
    {
        var writer = new RecordingOutboxWriter();
        var service = CreateService(writer);
        var post = PublishedPost();
        post.Status = PostStatus.Draft;
        var before = service.Observe(post);

        post.Publish();
        await service.RecordChangeAsync(post, before);

        Assert.Equal(1, post.ContentRevision);
        var message = Assert.Single(writer.Messages);
        Assert.Equal(AgentMessageTypes.ArticleContentChanged, message.MessageType);
        Assert.Equal(AgentMessageTypeRegistry.ContentExchange, message.Exchange);
        Assert.Equal("content.article.changed.v1", message.RoutingKey);

        var payload = EnvelopePayload(message.EnvelopeJson);
        Assert.Equal("updated", payload.GetProperty("action").GetString());
        Assert.Equal(1, payload.GetProperty("article_revision").GetInt64());
        Assert.Equal(post.Id.ToString("D"), payload.GetProperty("article_id").GetString());
        Assert.Equal(AgentContentEventComposer.ComputeContentHash(post.Content),
            payload.GetProperty("content_hash").GetString());
    }

    [Fact]
    public async Task Unpublish_WritesTombstoneWithoutContentHash()
    {
        var writer = new RecordingOutboxWriter();
        var service = CreateService(writer);
        var post = PublishedPost(revision: 3);
        var before = service.Observe(post);

        post.Unpublish();
        await service.RecordChangeAsync(post, before);

        Assert.Equal(4, post.ContentRevision);
        var payload = EnvelopePayload(Assert.Single(writer.Messages).EnvelopeJson);
        Assert.Equal("unpublished", payload.GetProperty("action").GetString());
        Assert.False(payload.TryGetProperty("content_hash", out _)); // B1: tombstone hash taşımaz
    }

    [Fact]
    public async Task SoftDeleteOfPublishedPost_WritesTombstone()
    {
        var writer = new RecordingOutboxWriter();
        var service = CreateService(writer);
        var post = PublishedPost(revision: 2);
        var before = service.Observe(post);

        post.IsDeleted = true;
        await service.RecordChangeAsync(post, before);

        Assert.Equal(3, post.ContentRevision);
        var payload = EnvelopePayload(Assert.Single(writer.Messages).EnvelopeJson);
        Assert.Equal("unpublished", payload.GetProperty("action").GetString());
    }

    [Fact]
    public async Task PublishedContentChange_IncrementsRevisionAndWritesUpdated()
    {
        var writer = new RecordingOutboxWriter();
        var service = CreateService(writer);
        var post = PublishedPost(revision: 5);
        var before = service.Observe(post);

        post.Content = "# Baslik\n\nGuncel icerik.";
        await service.RecordChangeAsync(post, before);

        Assert.Equal(6, post.ContentRevision);
        var payload = EnvelopePayload(Assert.Single(writer.Messages).EnvelopeJson);
        Assert.Equal("updated", payload.GetProperty("action").GetString());
        Assert.Equal(6, payload.GetProperty("article_revision").GetInt64());
    }

    [Fact]
    public async Task PublishedNoOpSave_ProducesNoEvent()
    {
        var writer = new RecordingOutboxWriter();
        var service = CreateService(writer);
        var post = PublishedPost(revision: 5);
        var before = service.Observe(post);

        post.ViewCount += 1; // görüntülenme gibi içerik dışı alan
        await service.RecordChangeAsync(post, before);

        Assert.Equal(5, post.ContentRevision); // revision DEĞİŞMEZ (plan B8: ilgisiz güncelleme)
        Assert.Empty(writer.Messages);
    }

    [Fact]
    public async Task RepublishedAfterUnpublish_GetsNextRevision()
    {
        var writer = new RecordingOutboxWriter();
        var service = CreateService(writer);
        var post = PublishedPost(revision: 4);
        var unpublishBefore = service.Observe(post);
        post.Unpublish();
        await service.RecordChangeAsync(post, unpublishBefore);

        var publishBefore = service.Observe(post);
        post.Publish();
        await service.RecordChangeAsync(post, publishBefore);

        Assert.Equal(6, post.ContentRevision);
        Assert.Equal(2, writer.Messages.Count);
        Assert.Equal("unpublished", EnvelopePayload(writer.Messages[0].EnvelopeJson).GetProperty("action").GetString());
        Assert.Equal("updated", EnvelopePayload(writer.Messages[1].EnvelopeJson).GetProperty("action").GetString());
    }

    [Fact]
    public async Task ComposedEnvelope_PassesContractValidator()
    {
        var writer = new RecordingOutboxWriter();
        var service = CreateService(writer);
        var post = PublishedPost(revision: 1);
        var before = service.Observe(post);
        post.Content = "# B\n\nYeni.";
        await service.RecordChangeAsync(post, before);

        var result = new AgentContractValidator().Validate(Assert.Single(writer.Messages).EnvelopeJson);
        Assert.True(result.IsValid, result.Error?.Message);
    }

    [Fact]
    public void ComputeContentHash_IsUtf8Sha256Lowercase()
    {
        var expected = Convert.ToHexString(
            System.Security.Cryptography.SHA256.HashData(System.Text.Encoding.UTF8.GetBytes("abc"))).ToLowerInvariant();
        Assert.Equal(expected, AgentContentEventComposer.ComputeContentHash("abc"));
        Assert.Equal("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad", expected);
    }

    private static System.Text.Json.JsonElement EnvelopePayload(string envelopeJson)
    {
        using var document = System.Text.Json.JsonDocument.Parse(envelopeJson);
        return document.RootElement.GetProperty("payload").Clone();
    }

    /// <summary>Test double: outbox kayıtlarını bellekte tutar (is_test_double karşılığı).</summary>
    public sealed class RecordingOutboxWriter : IOutboxWriter
    {
        public bool IsTestDouble => true;
        public List<OutboxMessage> Messages { get; } = [];

        public Task AddAsync(OutboxMessage message, CancellationToken cancellationToken = default)
        {
            Messages.Add(message);
            return Task.CompletedTask;
        }
    }
}
