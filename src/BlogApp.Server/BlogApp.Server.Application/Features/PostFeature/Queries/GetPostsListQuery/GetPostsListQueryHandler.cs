using AutoMapper;
using AutoMapper.QueryableExtensions;
using BlogApp.Server.Application.Common.Interfaces.Persistence;
using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.Features.PostFeature.DTOs;
using BlogApp.Server.Domain.Enums;
using MediatR;
using Microsoft.EntityFrameworkCore;

namespace BlogApp.Server.Application.Features.PostFeature.Queries.GetPostsListQuery;

public class GetPostsListQueryHandler(
    IUnitOfWork unitOfWork,
    IMapper mapper) : IRequestHandler<GetPostsListQueryRequest, GetPostsListQueryResponse>
{
    public async Task<GetPostsListQueryResponse> Handle(GetPostsListQueryRequest request, CancellationToken cancellationToken)
    {
        var isSearchQuery = !string.IsNullOrWhiteSpace(request.SearchTerm);

        // Base query - Include'lar ProjectTo ile otomatik yönetilir
        var query = unitOfWork.PostsRead.Query()
            .AsNoTracking()
            .IgnoreQueryFilters()
            .Where(p => !p.IsDeleted);

        // Status filtresi
        if (request.Status.HasValue)
        {
            query = query.Where(p => p.Status == request.Status.Value);
        }
        else
        {
            query = query.Where(p => p.Status == PostStatus.Published);
        }

        // Diğer filtreler
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

        if (request.IsFeatured.HasValue)
        {
            query = query.Where(p => p.IsFeatured == request.IsFeatured.Value);
        }

        // Arama işlemi
        if (isSearchQuery)
        {
            var searchTermLower = request.SearchTerm!.Trim().ToLower();
            var normalizedSearch = NormalizeTurkishCharacters(searchTermLower);
            
            // Tüm alanlarda arama - Türkçe karakter uyumlu (case-insensitive)
            // ToLower().Contains() PostgreSQL'de LOWER() ve LIKE kombinasyonuna çevrilir
            query = query.Where(p =>
                // Title araması
                p.Title.ToLower().Contains(searchTermLower) ||
                p.Title.ToLower().Contains(normalizedSearch) ||
                // Slug araması
                p.Slug.ToLower().Contains(searchTermLower) ||
                p.Slug.ToLower().Contains(normalizedSearch) ||
                // Content araması
                p.Content.ToLower().Contains(searchTermLower) ||
                p.Content.ToLower().Contains(normalizedSearch) ||
                // Excerpt araması
                (p.Excerpt != null && (
                    p.Excerpt.ToLower().Contains(searchTermLower) ||
                    p.Excerpt.ToLower().Contains(normalizedSearch)
                )) ||
                // Tag araması
                p.Tags.Any(t => 
                    t.Name.ToLower().Contains(searchTermLower) ||
                    t.Name.ToLower().Contains(normalizedSearch)
                ) ||
                // Category araması
                (p.Category != null && (
                    p.Category.Name.ToLower().Contains(searchTermLower) ||
                    p.Category.Name.ToLower().Contains(normalizedSearch)
                ))
            );

            // Relevance sıralama: title > tags > category > content
            query = query.OrderByDescending(p =>
                    // Title eşleşmesi en yüksek öncelik (3 puan)
                    (p.Title.ToLower().Contains(searchTermLower) ||
                     p.Title.ToLower().Contains(normalizedSearch) ? 3 : 0) +
                    // Tag eşleşmesi (2 puan)
                    (p.Tags.Any(t => 
                        t.Name.ToLower().Contains(searchTermLower) ||
                        t.Name.ToLower().Contains(normalizedSearch)
                    ) ? 2 : 0) +
                    // Category eşleşmesi (1 puan)
                    (p.Category != null && (
                        p.Category.Name.ToLower().Contains(searchTermLower) ||
                        p.Category.Name.ToLower().Contains(normalizedSearch)
                    ) ? 1 : 0)
                )
                .ThenByDescending(p => p.PublishedAt ?? p.CreatedAt);
        }
        else
        {
            // Normal sıralama
            query = request.SortBy.ToLowerInvariant() switch
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
        }

        var totalCount = await query.CountAsync(cancellationToken);

        var posts = await query
            .Skip((request.PageNumber - 1) * request.PageSize)
            .Take(request.PageSize)
            .ProjectTo<PostListQueryDto>(mapper.ConfigurationProvider)
            .ToListAsync(cancellationToken);

        var result = new PaginatedList<PostListQueryDto>(posts, totalCount, request.PageNumber, request.PageSize);

        return new GetPostsListQueryResponse { Result = result };
    }

    /// <summary>
    /// Türkçe karakterleri normalize eder (ı->i, ö->o, ü->u, ş->s, ğ->g, ç->c, İ->i)
    /// </summary>
    private static string NormalizeTurkishCharacters(string input)
    {
        if (string.IsNullOrEmpty(input)) return input;

        return input
            .Replace('ı', 'i')
            .Replace('İ', 'i')
            .Replace('ö', 'o')
            .Replace('Ö', 'o')
            .Replace('ü', 'u')
            .Replace('Ü', 'u')
            .Replace('ş', 's')
            .Replace('Ş', 's')
            .Replace('ğ', 'g')
            .Replace('Ğ', 'g')
            .Replace('ç', 'c')
            .Replace('Ç', 'c');
    }
}


