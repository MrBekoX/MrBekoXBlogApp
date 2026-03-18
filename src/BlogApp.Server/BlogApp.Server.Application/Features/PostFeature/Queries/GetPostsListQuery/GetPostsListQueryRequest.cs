using BlogApp.Server.Application.Common.Behaviors;
using BlogApp.Server.Application.Features.PostFeature.Constants; // PostCacheKeys için gerekli
using BlogApp.Server.Domain.Enums;
using MediatR;

namespace BlogApp.Server.Application.Features.PostFeature.Queries.GetPostsListQuery;

public class GetPostsListQueryRequest : IRequest<GetPostsListQueryResponse>, ICacheableQuery
{
    public int PageNumber { get; init; } = 1;
    public int PageSize { get; init; } = 10;
    public string? SearchTerm { get; init; }
    public Guid? CategoryId { get; init; }
    public Guid? TagId { get; init; }
    public Guid? AuthorId { get; init; }
    public PostStatus? Status { get; init; }
    public bool? IsFeatured { get; init; }
    public string SortBy { get; init; } = "CreatedAt";
    public bool SortDescending { get; init; } = true;

    // CacheKey: İsteğin parametrelerine göre benzersiz bir anahtar oluşturur
    public string CacheKey => $"posts-list-{PageNumber}-{PageSize}-{SearchTerm}-{CategoryId}-{TagId}-{AuthorId}-{Status}-{IsFeatured}-{SortBy}-{SortDescending}";

    // Cache süresi: arama sorguları için daha kısa
    public TimeSpan? CacheDuration => string.IsNullOrWhiteSpace(SearchTerm)
        ? TimeSpan.FromMinutes(10)
        : TimeSpan.FromMinutes(2);

    // Cache group for version-based invalidation
    public string? CacheGroup => PostCacheKeys.ListGroup;

    // Enable Stale-While-Revalidate for instant responses
    public bool UseStaleWhileRevalidate => true;

    // Soft expiration at 50% of hard (5 min soft, 10 min hard)
    public double SwrSoftRatio => 0.5;
}
