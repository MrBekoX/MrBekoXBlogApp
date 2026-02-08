using BlogApp.Server.Application.Common.BusinessRuleEngine;
using BlogApp.Server.Application.Common.Interfaces.Persistence;
using BlogApp.Server.Application.Common.Interfaces.Services;
using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Domain.Enums;
using MediatR;
using Microsoft.EntityFrameworkCore;
using BlogApp.Server.Application.Features.PostFeature.Constants;
using BlogApp.Server.Application.Features.PostFeature.Rules;
using BlogApp.Server.Domain.ValueObjects;
using Microsoft.Extensions.Logging;

namespace BlogApp.Server.Application.Features.PostFeature.Commands.UpdatePostCommand;

public class UpdatePostCommandHandler(
    IUnitOfWork unitOfWork,
    ICurrentUserService currentUserService,
    IPostBusinessRules postBusinessRules,
    ITagService tagService,
    ICacheService cacheService,
    ILogger<UpdatePostCommandHandler> logger,
    IHtmlSanitizerService htmlSanitizer) : IRequestHandler<UpdatePostCommandRequest, UpdatePostCommandResponse>
{
    public async Task<UpdatePostCommandResponse> Handle(UpdatePostCommandRequest request, CancellationToken cancellationToken)
    {
        var dto = request.UpdatePostCommandRequestDto!;

        // Business Rules
        var ruleResult = await BusinessRuleEngine.RunAsync(
            async () => await postBusinessRules.CheckPostExistsAsync(dto.Id)
        );

        if (!ruleResult.IsSuccess)
        {
            return new UpdatePostCommandResponse
            {
                Result = Result.Failure(ruleResult.Error!)
            };
        }

        // Include Tags to ensure EF Core tracks existing relationships correctly
        // This prevents "duplicate key violates unique constraint PK_post_tags" error
        var post = await unitOfWork.PostsRead.Query()
            .Include(p => p.Tags)
            .FirstOrDefaultAsync(p => p.Id == dto.Id, cancellationToken);
        if (post is null)
        {
            return new UpdatePostCommandResponse
            {
                Result = Result.Failure(PostBusinessRuleMessages.PostNotFoundGeneric)
            };
        }

        // BOLA check: Authors can only edit their own posts
        var currentUserId = currentUserService.UserId;
        if (!currentUserService.IsInRole("Admin") && !currentUserService.IsInRole("Editor")
            && post.AuthorId != currentUserId)
        {
            return new UpdatePostCommandResponse
            {
                Result = Result.Failure("You can only edit your own posts")
            };
        }

        // Cache invalidation için orijinal slug'ı sakla
        var originalSlug = post.Slug;

        // Başlık değiştiyse slug güncelle
        if (post.Title != dto.Title)
        {
            var newSlug = Slug.CreateFromTitle(dto.Title);
            var existingPost = await unitOfWork.PostsRead.GetSingleAsync(
                p => p.Slug == newSlug.Value && p.Id != dto.Id, cancellationToken);

            post.Slug = existingPost is not null
                ? $"{newSlug.Value}-{Guid.NewGuid().ToString()[..8]}"
                : newSlug.Value;
        }

        // Tag'leri al veya oluştur (batch query ile N+1 önleme)
        post.Tags.Clear();
        var tags = await tagService.GetOrCreateTagsAsync(dto.TagNames, cancellationToken);
        foreach (var tag in tags)
        {
            post.Tags.Add(tag);
        }

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

        // Diğer alanları güncelle
        post.Title = htmlSanitizer.Sanitize(dto.Title);
        post.Content = htmlSanitizer.Sanitize(dto.Content);
        post.Excerpt = htmlSanitizer.Sanitize(dto.Excerpt);
        post.FeaturedImageUrl = dto.FeaturedImageUrl;
        post.CategoryId = categoryId;
        // MetaTitle max 70 karakter limiti
        post.MetaTitle = dto.MetaTitle != null && dto.MetaTitle.Length <= 70
            ? htmlSanitizer.Sanitize(dto.MetaTitle)
            : (dto.Title.Length <= 70 ? htmlSanitizer.Sanitize(dto.Title) : htmlSanitizer.Sanitize(dto.Title)[..70]);
        post.MetaDescription = htmlSanitizer.Sanitize(dto.MetaDescription);
        post.MetaKeywords = htmlSanitizer.Sanitize(dto.MetaKeywords);
        post.IsFeatured = dto.IsFeatured;
        post.Status = status;
        post.UpdatedAt = DateTime.UtcNow;
        post.UpdatedBy = currentUserService.UserName;

        // AI-generated fields (only update if provided)
        if (dto.AiSummary != null)
            post.AiSummary = htmlSanitizer.Sanitize(dto.AiSummary);
        if (dto.AiKeywords != null)
            post.AiKeywords = htmlSanitizer.Sanitize(dto.AiKeywords);
        if (dto.AiEstimatedReadingTime.HasValue)
            post.AiEstimatedReadingTime = dto.AiEstimatedReadingTime.Value;
        if (dto.AiSeoDescription != null)
            post.AiSeoDescription = htmlSanitizer.Sanitize(dto.AiSeoDescription);
        if (dto.AiGeoOptimization != null)
            post.AiGeoOptimization = htmlSanitizer.Sanitize(dto.AiGeoOptimization);

        // Yayınlanma tarihi kontrolü
        if (status == PostStatus.Published && post.PublishedAt == null)
        {
            post.PublishedAt = DateTime.UtcNow;
        }

        // Okuma süresini yeniden hesapla
        post.CalculateReadingTime();

        try
        {
            await unitOfWork.PostsWrite.UpdateAsync(post, cancellationToken);
            await unitOfWork.SaveChangesAsync(cancellationToken);
        }
        catch (DbUpdateException ex)
        {
            // Handle database constraint violations
            if (ex.InnerException?.Message.Contains("duplicate key") == true)
            {
                return new UpdatePostCommandResponse
                {
                    Result = Result.Failure("A post with this slug already exists.")
                };
            }

            return new UpdatePostCommandResponse
            {
                Result = Result.Failure("Database error occurred while updating post.")
            };
        }
        catch (Exception ex)
        {
            // Log the exception details but don't expose them to the client
            logger.LogError(ex, "Unexpected error while updating post {PostId}", dto.Id);
            return new UpdatePostCommandResponse
            {
                Result = Result.Failure("An unexpected error occurred while updating the post. Please try again later.")
            };
        }

        // Cache invalidation
        // Invalidate by Id
        await cacheService.RemoveAsync(PostCacheKeys.ById(post.Id), cancellationToken);

        // Invalidate original slug cache
        await cacheService.RemoveAsync(PostCacheKeys.BySlug(originalSlug), cancellationToken);

        // If slug changed, also invalidate the new slug cache
        if (originalSlug != post.Slug)
        {
            await cacheService.RemoveAsync(PostCacheKeys.BySlug(post.Slug), cancellationToken);
        }

        // Rotate list cache version (content change affects lists)
        await cacheService.RotateGroupVersionAsync(PostCacheKeys.ListGroup, cancellationToken);

        return new UpdatePostCommandResponse
        {
            Result = Result.Success()
        };
    }
}



