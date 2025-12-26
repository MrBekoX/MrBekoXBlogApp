using BlogApp.Server.Application.Common.Behaviors;
using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.DTOs.Posts;
using BlogApp.Server.Domain.Enums;
using MediatR;

namespace BlogApp.Server.Application.Features.Posts.Queries.GetPostsList;

/// <summary>
/// Post listesi getirme sorgusu
/// </summary>
public record GetPostsListQuery : IRequest<PaginatedList<PostDto>>, ICacheableQuery
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

    public string CacheKey => $"posts-list-{PageNumber}-{PageSize}-{SearchTerm}-{CategoryId}-{TagId}-{AuthorId}-{Status}-{IsFeatured}-{SortBy}-{SortDescending}";
    public TimeSpan? CacheDuration => TimeSpan.FromMinutes(5);
}
