using BlogApp.Core.Application.Common.Errors;
using BlogApp.Core.Application.Common.Interfaces.Data;
using BlogApp.Core.Application.Common.Models;
using BlogApp.Core.Application.Features.AgentFeature.Services;
using BlogApp.Core.Domain.Enums;
using MediatR;
using Microsoft.EntityFrameworkCore;

namespace BlogApp.Core.Application.Features.AgentFeature.Queries.GetAgentInternalContentQuery;

/// <summary>Internal content sorgusu: yalnız Status=Published makaleler sunulur;
/// yok/draft/archived (ve silinmiş — global query filter) durumunda NotFound.
/// Okuma yolu makale erişim okumasıyla aynıdır (AsNoTracking + Published filtresi;
/// AcceptAgentRunCommandHandler adım 2). contentHash bellekte hesaplanır —
/// kabul anındaki ArticleContentHash ile BİREBİR aynı fonksiyon
/// (AgentArticleContentHash.Compute); revision kabul üçlüsünün article_revision
/// kaynağı olan BlogPost.ContentRevision'dan okunur (W5 bulgusu 4i).</summary>
public sealed class GetAgentInternalContentQueryHandler(IApplicationDbContext dbContext)
    : IRequestHandler<GetAgentInternalContentQueryRequest, Result<AgentInternalContentDto>>
{
    public async Task<Result<AgentInternalContentDto>> Handle(
        GetAgentInternalContentQueryRequest request,
        CancellationToken cancellationToken)
    {
        var article = await dbContext.Posts
            .AsNoTracking()
            .Include(p => p.Tags)
            .Where(p => p.Id == request.ArticleId && p.Status == PostStatus.Published)
            .FirstOrDefaultAsync(cancellationToken);

        if (article is null)
        {
            return Result<AgentInternalContentDto>.Failure(
                Error.NotFound("Makale bulunamadı veya agent sorularına açık değil."));
        }

        var dto = new AgentInternalContentDto
        {
            ArticleId = article.Id,
            Revision = article.ContentRevision,
            ContentHash = AgentArticleContentHash.Compute(article.Content),
            Title = article.Title,
            Content = article.Content,
            Tags = article.Tags.Select(t => t.Name).ToList(),
            PublishedAt = article.PublishedAt is { } published
                ? new DateTimeOffset(published, TimeSpan.Zero)
                : null,
        };

        return Result<AgentInternalContentDto>.Success(dto);
    }
}
