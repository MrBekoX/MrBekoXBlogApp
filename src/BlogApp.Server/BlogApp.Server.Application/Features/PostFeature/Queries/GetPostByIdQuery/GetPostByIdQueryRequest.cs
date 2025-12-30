using BlogApp.Server.Application.Common.Behaviors;
using BlogApp.Server.Application.Features.PostFeature.Constants;
using MediatR;

namespace BlogApp.Server.Application.Features.PostFeature.Queries.GetPostByIdQuery;

public class GetPostByIdQueryRequest : IRequest<GetPostByIdQueryResponse>, ICacheableQuery
{
    public Guid Id { get; set; }

    public string CacheKey => PostCacheKeys.ById(Id);

    // No group versioning for individual posts - they're invalidated directly
    public string? CacheGroup => null;

    // Individual posts can be cached longer since they're invalidated on update
    public TimeSpan? CacheDuration => TimeSpan.FromMinutes(10);
}
