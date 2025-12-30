using AutoMapper;
using AutoMapper.QueryableExtensions;
using BlogApp.Server.Application.Common.Interfaces;
using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.Features.PostFeature.Constants;
using BlogApp.Server.Application.Features.PostFeature.DTOs;
using BlogApp.Server.Domain.Enums;
using MediatR;
using Microsoft.EntityFrameworkCore;

namespace BlogApp.Server.Application.Features.PostFeature.Queries.GetPostsListQuery;

public class GetPostsListQueryHandler(
    IUnitOfWork unitOfWork,
    ICacheService cacheService,
    IMapper mapper) : IRequestHandler<GetPostsListQueryRequest, GetPostsListQueryResponse>
{
    private static readonly TimeSpan CacheDuration = TimeSpan.FromMinutes(5);

    public async Task<GetPostsListQueryResponse> Handle(GetPostsListQueryRequest request, CancellationToken cancellationToken)
    {
        var shouldCache = ShouldUseCache(request);

        var version = shouldCache
            ? await cacheService.GetGroupVersionAsync(PostCacheKeys.ListGroup, cancellationToken)
            : 0L;

        var cacheKey = GenerateCacheKey(request, (int)version);

        if (shouldCache)
        {
            var cachedResult = await cacheService.GetAsync<PaginatedList<PostListQueryDto>>(cacheKey, cancellationToken);
            if (cachedResult != null)
            {
                return new GetPostsListQueryResponse { Result = cachedResult };
            }
        }

        // DÜZELTME BURADA: IgnoreQueryFilters() eklendi.
        // Bu sayede User tablosundaki global filtreler (IsDeleted vs) Post sorgusunu bozmayacak.
        var query = unitOfWork.PostsRead.Query()
            .AsNoTracking()
            .IgnoreQueryFilters()
            .Include(p => p.Author)
            .Include(p => p.Category)
            .Include(p => p.Tags)
            .Where(p => !p.IsDeleted); // Post'un kendi silinme kontrolünü manuel ekliyoruz

        // Filtreleme
        if (!string.IsNullOrWhiteSpace(request.SearchTerm))
        {
            var searchTerm = request.SearchTerm.ToLower();
            query = query.Where(p =>
                p.Title.ToLower().Contains(searchTerm) ||
                p.Content.ToLower().Contains(searchTerm) ||
                (p.Excerpt != null && p.Excerpt.ToLower().Contains(searchTerm)));
        }

        if (request.CategoryId.HasValue)
        {
            query = query.Where(p => p.CategoryId == request.CategoryId.Value);
        }

        if (request.TagId.HasValue)
        {
            query = query.Where(p => p.Tags.Any(t => t.Id == request.TagId.Value));
        }

        if (request.AuthorId.HasValue)
        {
            query = query.Where(p => p.AuthorId == request.AuthorId.Value);
        }

        if (request.Status.HasValue)
        {
            query = query.Where(p => p.Status == request.Status.Value);
        }
        else
        {
            query = query.Where(p => p.Status == PostStatus.Published);
        }

        if (request.IsFeatured.HasValue)
        {
            query = query.Where(p => p.IsFeatured == request.IsFeatured.Value);
        }

        // Sıralama
        query = request.SortBy.ToLower() switch
        {
            "title" => request.SortDescending
                ? query.OrderByDescending(p => p.Title)
                : query.OrderBy(p => p.Title),
            "viewcount" => request.SortDescending
                ? query.OrderByDescending(p => p.ViewCount)
                : query.OrderBy(p => p.ViewCount),
            "publishedat" => request.SortDescending
                ? query.OrderByDescending(p => p.PublishedAt)
                : query.OrderBy(p => p.PublishedAt),
            _ => request.SortDescending
                ? query.OrderByDescending(p => p.CreatedAt)
                : query.OrderBy(p => p.CreatedAt)
        };

        var totalCount = await query.CountAsync(cancellationToken);

        var posts = await query
            .Skip((request.PageNumber - 1) * request.PageSize)
            .Take(request.PageSize)
            .ProjectTo<PostListQueryDto>(mapper.ConfigurationProvider)
            .ToListAsync(cancellationToken);

        var result = new PaginatedList<PostListQueryDto>(posts, totalCount, request.PageNumber, request.PageSize);

        if (shouldCache)
        {
            await cacheService.SetAsync(cacheKey, result, CacheDuration, cancellationToken);
        }

        return new GetPostsListQueryResponse { Result = result };
    }

    private static string GenerateCacheKey(GetPostsListQueryRequest request, int version)
    {
        var keySuffix = $"{request.PageNumber}:{request.PageSize}:{request.Status}:" +
                        $"{request.CategoryId}:{request.TagId}:{request.IsFeatured}:" +
                        $"{request.SortBy}:{request.SortDescending}:{request.SearchTerm ?? ""}";
        return PostCacheKeys.VersionedListKey(version, keySuffix);
    }

    private static bool ShouldUseCache(GetPostsListQueryRequest request)
    {
        return (request.Status == null || request.Status == PostStatus.Published)
               && string.IsNullOrEmpty(request.SearchTerm)
               && request.AuthorId == null;
    }
}