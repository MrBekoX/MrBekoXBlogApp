using MediatR;
using BlogApp.Core.Application.Common.Models;

namespace BlogApp.Core.Application.Features.AgentFeature.Queries.GetAgentInternalContentQuery;

/// <summary>GET /api/v1/agent/internal/content/{articleId} isteği; servis anahtarı
/// Presentation'da (AgentInternalEndpoints) sabit zamanlı doğrulanır, sorgu yalnız
/// yayımlanmış makalenin anlık görüntüsünü döndürür (Python agent retrieval kaynağı).</summary>
public sealed record GetAgentInternalContentQueryRequest : IRequest<Result<AgentInternalContentDto>>
{
    public required Guid ArticleId { get; init; }
}

/// <summary>Internal content yanıtı (sabit sözleşme): alan adları wire'da camelCase
/// olarak ve birebir taşınır (articleId, revision, contentHash, title, content,
/// tags, publishedAt). revision kaynağı BlogPost.ContentRevision'dır — kabul
/// anında AgentRun.ArticleRevision'a yazılan değerin AYNI kaynağı
/// (AcceptAgentRunCommandHandler.BuildContextSnapshot). contentHash
/// AgentArticleContentHash.Compute ile üretilir — kabul anındaki
/// AgentRun.ArticleContentHash ile BİREBİR aynı fonksiyondur; aksi halde worker
/// stale_snapshot guard'ı koşuyu düşürür.</summary>
public sealed record AgentInternalContentDto
{
    public required Guid ArticleId { get; init; }

    public required long Revision { get; init; }

    public required string ContentHash { get; init; }

    public required string Title { get; init; }

    public required string Content { get; init; }

    public IReadOnlyList<string> Tags { get; init; } = [];

    public DateTimeOffset? PublishedAt { get; init; }
}
