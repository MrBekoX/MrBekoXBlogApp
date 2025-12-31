using BlogApp.Server.Application.Common.Interfaces.Persistence;
using BlogApp.Server.Application.Common.Interfaces.Services;
using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.Features.PostFeature.Constants;
using BlogApp.Server.Domain.Entities;
using BlogApp.Server.Domain.Enums;
using BlogApp.Server.Domain.ValueObjects;
using MediatR;

namespace BlogApp.Server.Application.Features.PostFeature.Commands.CreatePostCommand;

public class CreatePostCommandHandler(
    IUnitOfWork unitOfWork,
    ICurrentUserService currentUserService,
    ITagService tagService,
    ICacheService cacheService) : IRequestHandler<CreatePostCommandRequest, CreatePostCommandResponse>
{
    public async Task<CreatePostCommandResponse> Handle(CreatePostCommandRequest request, CancellationToken cancellationToken)
    {
        if (currentUserService.UserId is null)
        {
            return new CreatePostCommandResponse
            {
                Result = Result<Guid>.Failure(PostBusinessRuleMessages.UserNotAuthenticated)
            };
        }

        var dto = request.CreatePostCommandRequestDto!;

        // Slug oluştur - benzersiz olması için timestamp ekle
        var baseSlug = Slug.CreateFromTitle(dto.Title);
        var timestamp = DateTime.UtcNow.Ticks.ToString()[^8..];
        var slug = Slug.Create($"{baseSlug.Value}-{timestamp}");

        // Tag'leri al veya oluştur (batch query ile N+1 önleme)
        var tags = await tagService.GetOrCreateTagsAsync(dto.TagNames, cancellationToken);

        // İlk kategoriyi al
        Guid? categoryId = dto.CategoryIds.FirstOrDefault();
        if (categoryId == Guid.Empty) categoryId = null;

        // Status'u parse et
        var status = dto.Status switch
        {
            "Published" => PostStatus.Published,
            "Archived" => PostStatus.Archived,
            _ => PostStatus.Draft
        };

        // Post oluştur
        var post = new BlogPost
        {
            Id = Guid.NewGuid(),
            Title = dto.Title,
            Slug = slug.Value,
            Content = dto.Content,
            Excerpt = dto.Excerpt,
            FeaturedImageUrl = dto.FeaturedImageUrl,
            CategoryId = categoryId,
            AuthorId = currentUserService.UserId.Value,
            MetaTitle = dto.MetaTitle ?? dto.Title,
            MetaDescription = dto.MetaDescription,
            MetaKeywords = dto.MetaKeywords,
            Status = status,
            PublishedAt = status == PostStatus.Published ? DateTime.UtcNow : null,
            Tags = tags,
            CreatedAt = DateTime.UtcNow,
            CreatedBy = currentUserService.UserName
        };

        post.CalculateReadingTime();

        await unitOfWork.PostsWrite.AddAsync(post, cancellationToken);
        await unitOfWork.SaveChangesAsync(cancellationToken);

        // Published post eklendiyse liste cache versiyonunu rotate et
        if (status == PostStatus.Published)
        {
            await cacheService.RotateGroupVersionAsync(PostCacheKeys.ListGroup, cancellationToken);
        }

        return new CreatePostCommandResponse
        {
            Result = Result<Guid>.Success(post.Id)
        };
    }
}



