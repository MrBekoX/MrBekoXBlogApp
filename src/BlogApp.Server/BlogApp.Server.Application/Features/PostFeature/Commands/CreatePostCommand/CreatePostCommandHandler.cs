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
    ICacheService cacheService,
    IHtmlSanitizerService htmlSanitizer) : IRequestHandler<CreatePostCommandRequest, CreatePostCommandResponse>
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
        // Slug max 250 karakter, timestamp 8 karakter + tire = 9 karakter
        // Base slug için max 241 karakter bırakıyoruz
        var baseSlug = Slug.CreateFromTitle(dto.Title);
        var timestamp = DateTime.UtcNow.Ticks.ToString()[^8..];
        var slugValue = $"{baseSlug.Value}-{timestamp}";
        
        // Slug uzunluğunu kontrol et (max 250 karakter)
        if (slugValue.Length > 250)
        {
            var maxBaseLength = 250 - 9; // 9 = "-" + 8 karakter timestamp
            slugValue = $"{baseSlug.Value[..Math.Min(baseSlug.Value.Length, maxBaseLength)].TrimEnd('-')}-{timestamp}";
        }
        
        var slug = Slug.Create(slugValue);

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
            Title = htmlSanitizer.Sanitize(dto.Title) ?? string.Empty,
            Slug = slug.Value,
            // Content is raw markdown — skip HTML sanitization to preserve code blocks
            Content = dto.Content ?? string.Empty,
            Excerpt = htmlSanitizer.Sanitize(dto.Excerpt),
            FeaturedImageUrl = dto.FeaturedImageUrl,
            CategoryId = categoryId,
            AuthorId = currentUserService.UserId.Value,
            MetaTitle = dto.MetaTitle != null && dto.MetaTitle.Length <= 70 
                ? htmlSanitizer.Sanitize(dto.MetaTitle) 
                : ((dto.Title?.Length ?? 0) <= 70 ? htmlSanitizer.Sanitize(dto.Title) : htmlSanitizer.Sanitize(dto.Title)?[..70]),
            MetaDescription = htmlSanitizer.Sanitize(dto.MetaDescription),
            MetaKeywords = htmlSanitizer.Sanitize(dto.MetaKeywords),
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
            try
            {
                await cacheService.RotateGroupVersionAsync(PostCacheKeys.ListGroup, cancellationToken);
            }
            catch (Exception ex)
            {
                // Cache rotation failure should not fail the entire operation
                // Consider logging this error
            }
        }

        return new CreatePostCommandResponse
        {
            Result = Result<Guid>.Success(post.Id)
        };
    }
}



