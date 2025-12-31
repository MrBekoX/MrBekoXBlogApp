using BlogApp.Server.Application.Common.Behaviors;
using BlogApp.Server.Application.Features.PostFeature.Constants;
using MediatR;

namespace BlogApp.Server.Application.Features.PostFeature.Queries.GetPostBySlugQuery;

public class GetPostBySlugQueryRequest : IRequest<GetPostBySlugQueryResponse>, ICacheableQuery
{
    public string Slug { get; set; } = default!;
    public bool IncrementViewCount { get; set; } = true;

    // Cache key: Only cache when NOT incrementing view count (read-only requests)
    // Empty key signals CachingBehavior to skip caching
    public string CacheKey => IncrementViewCount ? string.Empty : PostCacheKeys.BySlug(Slug);

    // No group versioning for individual posts - they're invalidated directly by slug
    public string? CacheGroup => null;

    // Individual posts can be cached longer since they're invalidated on update
    public TimeSpan? CacheDuration => TimeSpan.FromMinutes(10);
}

