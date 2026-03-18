using BlogApp.Server.Application.Common.Behaviors;
using BlogApp.Server.Application.Features.PostFeature.Constants;
using MediatR;

namespace BlogApp.Server.Application.Features.PostFeature.Queries.GetPostByIdQuery;

public class GetPostByIdQueryRequest : IRequest<GetPostByIdQueryResponse>, ICacheableQuery
{
    public Guid Id { get; set; }

    /// <summary>
    /// When true, only returns published posts. Private reads bypass shared cache.
    /// </summary>
    public bool RequirePublishedStatus { get; set; }

    public string CacheKey => RequirePublishedStatus ? PostCacheKeys.ById(Id) : string.Empty;

    public string? CacheGroup => null;

    public TimeSpan? CacheDuration => TimeSpan.FromMinutes(10);
}
