using AutoMapper;
using AutoMapper.QueryableExtensions;
using BlogApp.Server.Application.Common.Interfaces;
using BlogApp.Server.Application.Common.Models;
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
        // Cache key oluştur
        var cacheKey = GenerateCacheKey(request);

        // Sadece published ve basit istekleri cache'le
        var shouldCache = ShouldUseCache(request);

        if (shouldCache)
        {
            var cachedResult = await cacheService.GetAsync<PaginatedList<PostListQueryDto>>(cacheKey, cancellationToken);
            if (cachedResult != null)
            {
                return new GetPostsListQueryResponse { Result = cachedResult };
            }
        }

        var query = unitOfWork.PostsRead.Query()
            .AsNoTracking()
            .Include(p => p.Author)
            .Include(p => p.Category)
            .Include(p => p.Tags)
            .Where(p => !p.IsDeleted);

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
            // Varsayılan olarak sadece yayınlanmış yazıları getir
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

        // Toplam sayı
        var totalCount = await query.CountAsync(cancellationToken);

        // Sayfalama ve DTO'ya dönüştürme (AutoMapper ProjectTo kullanarak)
        var posts = await query
            .Skip((request.PageNumber - 1) * request.PageSize)
            .Take(request.PageSize)
            .ProjectTo<PostListQueryDto>(mapper.ConfigurationProvider)
            .ToListAsync(cancellationToken);

        var result = new PaginatedList<PostListQueryDto>(posts, totalCount, request.PageNumber, request.PageSize);

        // Cache'e kaydet
        if (shouldCache)
        {
            await cacheService.SetAsync(cacheKey, result, CacheDuration, cancellationToken);
        }

        return new GetPostsListQueryResponse { Result = result };
    }

    private static string GenerateCacheKey(GetPostsListQueryRequest request)
    {
        return $"posts:list:{request.PageNumber}:{request.PageSize}:{request.Status}:" +
               $"{request.CategoryId}:{request.TagId}:{request.IsFeatured}:" +
               $"{request.SortBy}:{request.SortDescending}:{request.SearchTerm ?? ""}";
    }

    private static bool ShouldUseCache(GetPostsListQueryRequest request)
    {
        // Sadece published postlar ve arama yoksa cache'le
        return (request.Status == null || request.Status == PostStatus.Published)
               && string.IsNullOrEmpty(request.SearchTerm)
               && request.AuthorId == null;
    }
}
