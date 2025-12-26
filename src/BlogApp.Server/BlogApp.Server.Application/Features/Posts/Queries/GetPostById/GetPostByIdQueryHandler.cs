using BlogApp.Server.Application.Common.Interfaces;
using BlogApp.Server.Application.DTOs.Posts;
using BlogApp.Server.Domain.Exceptions;
using MediatR;
using Microsoft.EntityFrameworkCore;

namespace BlogApp.Server.Application.Features.Posts.Queries.GetPostById;

/// <summary>
/// GetPostByIdQuery handler
/// </summary>
public class GetPostByIdQueryHandler : IRequestHandler<GetPostByIdQuery, PostDetailDto?>
{
    private readonly IUnitOfWork _unitOfWork;

    public GetPostByIdQueryHandler(IUnitOfWork unitOfWork)
    {
        _unitOfWork = unitOfWork;
    }

    public async Task<PostDetailDto?> Handle(GetPostByIdQuery request, CancellationToken cancellationToken)
    {
        var post = await _unitOfWork.Posts.Query()
            .AsNoTracking()
            .Include(p => p.Author)
            .Include(p => p.Category)
            .Include(p => p.Tags)
            .Include(p => p.Comments)
            .Where(p => p.Id == request.Id && !p.IsDeleted)
            .FirstOrDefaultAsync(cancellationToken);

        if (post is null)
            throw new NotFoundException(nameof(post), request.Id);

        return new PostDetailDto
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
    }
}
