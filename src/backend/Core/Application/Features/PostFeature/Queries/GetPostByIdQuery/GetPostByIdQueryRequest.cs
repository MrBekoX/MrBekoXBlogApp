using BlogApp.Core.Application.Common.Behaviors;
using BlogApp.Core.Application.Common.Models;
using BlogApp.Core.Application.Features.PostFeature.Constants;
using BlogApp.Core.Application.Features.PostFeature.DTOs;
using MediatR;

namespace BlogApp.Core.Application.Features.PostFeature.Queries.GetPostByIdQuery;

public class GetPostByIdQueryRequest : IRequest<Result<PostDetailQueryDto>>, ICacheableQuery
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
