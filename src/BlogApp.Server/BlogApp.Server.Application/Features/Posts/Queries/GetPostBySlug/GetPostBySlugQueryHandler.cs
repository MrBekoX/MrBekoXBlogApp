using BlogApp.Server.Application.Common.Interfaces;
using BlogApp.Server.Application.DTOs.Posts;
using BlogApp.Server.Domain.Enums;
using BlogApp.Server.Domain.Exceptions;
using MediatR;
using Microsoft.EntityFrameworkCore;

namespace BlogApp.Server.Application.Features.Posts.Queries.GetPostBySlug;

/// <summary>
/// GetPostBySlugQuery handler
/// </summary>
public class GetPostBySlugQueryHandler : IRequestHandler<GetPostBySlugQuery, PostDetailDto?>
{
    private readonly IUnitOfWork _unitOfWork;
    private readonly ICacheService _cacheService;
    private static readonly TimeSpan CacheDuration = TimeSpan.FromMinutes(10);

    public GetPostBySlugQueryHandler(IUnitOfWork unitOfWork, ICacheService cacheService)
    {
        _unitOfWork = unitOfWork;
        _cacheService = cacheService;
    }

    public async Task<PostDetailDto?> Handle(GetPostBySlugQuery request, CancellationToken cancellationToken)
    {
        var cacheKey = $"post:slug:{request.Slug}";
        
        // View count artırılmayacaksa cache'den al
        if (!request.IncrementViewCount)
        {
            var cachedResult = await _cacheService.GetAsync<PostDetailDto>(cacheKey, cancellationToken);
            if (cachedResult != null)
                return cachedResult;
        }
        
        var post = await _unitOfWork.Posts.Query()
            .Include(p => p.Author)
            .Include(p => p.Category)
            .Include(p => p.Tags)
            .Include(p => p.Comments)
            .Where(p => p.Slug == request.Slug && !p.IsDeleted && p.Status == PostStatus.Published)
            .FirstOrDefaultAsync(cancellationToken);

        if (post is null)
            throw new NotFoundException("Post", request.Slug);

        // View count artır
        if (request.IncrementViewCount)
        {
            post.ViewCount++;
            _unitOfWork.Posts.Update(post);
            await _unitOfWork.SaveChangesAsync(cancellationToken);
        }

        var result = new PostDetailDto
        {
            Id = post.Id,
            Title = post.Title,
            Slug = post.Slug,
            Content = post.Content,
            Excerpt = post.Excerpt,
            FeaturedImageUrl = post.FeaturedImageUrl,
            Status = post.Status,
            PublishedAt = post.PublishedAt,
            ViewCount = post.ViewCount,
            LikeCount = post.LikeCount,
            IsFeatured = post.IsFeatured,
            ReadingTimeMinutes = post.ReadingTimeMinutes,
            MetaTitle = post.MetaTitle,
            MetaDescription = post.MetaDescription,
            MetaKeywords = post.MetaKeywords,
            CommentCount = post.Comments.Count(c => c.IsApproved),
            CreatedAt = post.CreatedAt,
            Author = new AuthorDto
            {
                Id = post.Author.Id,
                UserName = post.Author.UserName,
                FullName = post.Author.FullName,
                AvatarUrl = post.Author.AvatarUrl,
                Bio = post.Author.Bio
            },
            Category = post.Category is not null
                ? new CategoryDto
                {
                    Id = post.Category.Id,
                    Name = post.Category.Name,
                    Slug = post.Category.Slug
                }
                : null,
            Tags = post.Tags.Select(t => new TagDto
            {
                Id = t.Id,
                Name = t.Name,
                Slug = t.Slug
            }).ToList()
        };
        
        // Cache'e kaydet
        await _cacheService.SetAsync(cacheKey, result, CacheDuration, cancellationToken);
        
        return result;
    }
}
