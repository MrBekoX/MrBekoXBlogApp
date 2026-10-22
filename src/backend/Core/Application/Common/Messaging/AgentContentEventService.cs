using BlogApp.Core.Application.Common.Interfaces.Messaging;
using BlogApp.Core.Application.Common.Options;
using BlogApp.Core.Domain.Entities;
using BlogApp.Core.Domain.Enums;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;

namespace BlogApp.Core.Application.Common.Messaging;

/// <summary>
/// <see cref="IAgentContentEventService"/> gerçekleştimi (B8). Karar tablosu
/// (before = Observe anı, now = RecordChange anı; "yayında" = Status==Published ve
/// !IsDeleted — GetPostBySlugQuery erişim tanımıyla aynıdır):
///
/// | before      | now         | fiil                          | revision | olay                       |
/// |-------------|-------------|-------------------------------|----------|----------------------------|
/// | yayında değil| yayında değil| taslak yaşam döngüsü          | değişmez | YOK (taslak taşınmaz)      |
/// | yayında değil| yayında     | görünürlük kazanımı (publish) | +1       | updated (content_hash'li)  |
/// | yayında     | yayında değil| görünürlük kaybı (unpublish/  | +1       | unpublished (TOMBSTONE)    |
/// |             |             | arşiv/soft delete)            |          |                            |
/// | yayında     | yayında     | özet aynı → no-op kaydetme    | değişmez | YOK                        |
/// | yayında     | yayında     | özet farklı → içerik değişti  | +1       | updated (content_hash'li)  |
///
/// Revision, yayımlanmış içerik anı kimliğidir (D008); BlogPost.Version (xmin)
/// KULLANILMAZ (L004). Zarf commit'ten ÖNCE B1 sözleşme doğrulayıcısından geçer;
/// doğrulama başarısızsa işlem istisna ile biter ve makale kaydı commit'lenmez
/// (kabul: bozuk zarf broker'a hiç ulaşamaz).
/// </summary>
public sealed class AgentContentEventService(
    IOutboxWriter outboxWriter,
    IOptions<AgentMessagingSettings> messagingOptions,
    ILogger<AgentContentEventService> logger) : IAgentContentEventService
{
    public const string ActionUpdated = "updated";
    public const string ActionUnpublished = "unpublished";

    private readonly AgentMessagingSettings _settings = messagingOptions.Value;

    public ArticleContentObservation Observe(BlogPost post) =>
        new(IsPublished(post), post is null ? null : AgentContentEventComposer.ComputeContentHash(post.Content));

    public async Task RecordChangeAsync(BlogPost post, ArticleContentObservation before, CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(post);

        var wasPublished = before.WasPublished;
        var nowPublished = IsPublished(post);

        if (!wasPublished && !nowPublished)
        {
            // Taslak içerik olayla TAŞINMAZ (plan B8); revision yayımlanmış an kimliğidir.
            return;
        }

        if (!wasPublished && nowPublished)
        {
            post.ContentRevision += 1;
            await WriteArticleChangedAsync(
                post, ActionUpdated, AgentContentEventComposer.ComputeContentHash(post.Content), cancellationToken);
            return;
        }

        if (wasPublished && !nowPublished)
        {
            post.ContentRevision += 1;
            await WriteArticleChangedAsync(post, ActionUnpublished, contentHash: null, cancellationToken);
            return;
        }

        var nowHash = AgentContentEventComposer.ComputeContentHash(post.Content);
        if (string.Equals(before.ContentHash, nowHash, StringComparison.Ordinal))
        {
            // No-op güncelleme (ör. görüntülenme dışı alan dokunuşu): yeni yayın anı değildir.
            return;
        }

        post.ContentRevision += 1;
        await WriteArticleChangedAsync(post, ActionUpdated, nowHash, cancellationToken);
    }

    private async Task WriteArticleChangedAsync(BlogPost post, string action, string? contentHash, CancellationToken cancellationToken)
    {
        var (envelopeJson, messageId) = AgentContentEventComposer.ComposeArticleChanged(
            articleId: post.Id,
            articleRevision: post.ContentRevision,
            action: action,
            contentHash: contentHash,
            language: null,
            title: post.Title,
            producer: _settings.ProducerName);

        var contractResult = new AgentContractValidator(_settings).Validate(envelopeJson);
        if (!contractResult.IsValid)
        {
            logger.LogError(
                "[AgentContent] zarf sözleşme doğrulaması reddetti: article {ArticleId} revision {Revision} action {Action} field {Field} {Detail}",
                post.Id, post.ContentRevision, action, contractResult.Error?.Field, contractResult.Error?.Message);
            throw new InvalidOperationException(
                $"İçerik olayı sözleşme doğrulamasını geçemedi ({contractResult.Error?.Field}: {contractResult.Error?.Message}); makale değişikliği commit edilmedi.");
        }

        await outboxWriter.AddAsync(new OutboxMessage
        {
            MessageId = messageId,
            MessageType = AgentMessageTypes.ArticleContentChanged,
            Exchange = AgentMessageTypeRegistry.ContentExchange,
            RoutingKey = AgentMessageTypeRegistry.RoutingKeyFor(
                AgentMessageTypeRegistry.ContentSchemaVersion, AgentMessageTypes.ArticleContentChanged),
            CorrelationId = messageId,
            EnvelopeJson = envelopeJson,
            Status = AgentOutboxStatus.Pending,
        }, cancellationToken);

        logger.LogInformation(
            "[AgentContent] içerik olayı outbox'a yazıldı: article {ArticleId} revision {Revision} action {Action} message_id {MessageId}",
            post.Id, post.ContentRevision, action, messageId);
    }

    private static bool IsPublished(BlogPost? post) =>
        post is not null && !post.IsDeleted && post.Status == PostStatus.Published;
}
