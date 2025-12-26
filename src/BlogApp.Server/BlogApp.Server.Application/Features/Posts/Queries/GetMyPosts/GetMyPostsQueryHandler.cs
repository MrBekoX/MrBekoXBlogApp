using BlogApp.Server.Application.Common.Interfaces;
using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.DTOs.Posts;
using MediatR;
using Microsoft.EntityFrameworkCore;

namespace BlogApp.Server.Application.Features.Posts.Queries.GetMyPosts;

/// <summary>
/// GetMyPostsQuery handler
/// </summary>
public class GetMyPostsQueryHandler : IRequestHandler<GetMyPostsQuery, PaginatedList<PostDto>>
{
    private readonly IUnitOfWork _unitOfWork;

    public GetMyPostsQueryHandler(IUnitOfWork unitOfWork)
    {
        _unitOfWork = unitOfWork;
    }

    public async Task<PaginatedList<PostDto>> Handle(GetMyPostsQuery request, CancellationToken cancellationToken)
    {
        var query = _unitOfWork.Posts.Query()
            .AsNoTracking()
            .Include(p => p.Author)
            .Include(p => p.Category)
            .Include(p => p.Tags)
            .Where(p => !p.IsDeleted && p.AuthorId == request.UserId)
            .OrderByDescending(p => p.CreatedAt);

        // Toplam sayı
        var totalCount = await query.CountAsync(cancellationToken);

        // Sayfalama ve DTO'ya dönüştürme
        var posts = await query
            .Skip((request.PageNumber - 1) * request.PageSize)
            .Take(request.PageSize)
            .Select(p => new PostDto
            {
                Id = p.Id,
                Title = p.Title,
                Slug = p.Slug,
                Excerpt = p.Excerpt ?? (p.Content.Length > 200 ? p.Content.Substring(0, 200) + "..." : p.Content),
                FeaturedImageUrl = p.FeaturedImageUrl,
                Status = p.Status,
                PublishedAt = p.PublishedAt,
                ViewCount = p.ViewCount,
                LikeCount = p.LikeCount,
                IsFeatured = p.IsFeatured,
                ReadingTimeMinutes = p.ReadingTimeMinutes,
                CreatedAt = p.CreatedAt,
                Author = new AuthorDto
                {
                    Id = p.Author.Id,
                    UserName = p.Author.UserName,
                    FullName = p.Author.FullName,
                    AvatarUrl = p.Author.AvatarUrl
                },
                Category = p.Category != null
                    ? new CategoryDto
                    {
                        Id = p.Category.Id,
                        Name = p.Category.Name,
                        Slug = p.Category.Slug
                    }
                    : null,
                Tags = p.Tags.Select(t => new TagDto
                {
                    Id = t.Id,
                    Name = t.Name,
                    Slug = t.Slug
                }).ToList()
            })
            .ToListAsync(cancellationToken);

        return new PaginatedList<PostDto>(posts, totalCount, request.PageNumber, request.PageSize);
    }
}

