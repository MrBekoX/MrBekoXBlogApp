using BlogApp.Server.Application.Common.Behaviors;
using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.Features.PostFeature.Constants;
using BlogApp.Server.Application.Features.PostFeature.DTOs;
using MediatR;

namespace BlogApp.Server.Application.Features.PostFeature.Queries.GetPostByIdQuery;

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
