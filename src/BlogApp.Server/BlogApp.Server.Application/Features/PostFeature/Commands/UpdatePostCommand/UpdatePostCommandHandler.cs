using BlogApp.Server.Application.Common.BusinessRuleEngine;
using BlogApp.Server.Application.Common.Interfaces.Persistence;
using BlogApp.Server.Application.Common.Interfaces.Services;
using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Domain.Enums;
using MediatR;
using Microsoft.EntityFrameworkCore;
using BlogApp.Server.Application.Features.PostFeature.Constants;
using BlogApp.Server.Application.Features.PostFeature.Rules;
using BlogApp.Server.Domain.Exceptions;
using BlogApp.Server.Domain.ValueObjects;
namespace BlogApp.Server.Application.Features.PostFeature.Commands.UpdatePostCommand;

public class UpdatePostCommandHandler(
    IUnitOfWork unitOfWork,
    ICurrentUserService currentUserService,
    IPostBusinessRules postBusinessRules,
    ITagService tagService,
    ICacheService cacheService,
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
        // Use AsTracking() to override default AsNoTracking() from Query()
        // This prevents "duplicate key violates unique constraint PK_post_tags" error
        var post = await unitOfWork.PostsRead.Query()
            .Include(p => p.Tags)
            .AsTracking()
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
        // FIX: Entity tracking çakışmasını önlemek için diff-based update yap
        // Mevcut tag'leri koru, sadece değişenleri işle

        // Tag isimlerini normalize et
        var normalizedTagNames = dto.TagNames
            .Where(t => !string.IsNullOrWhiteSpace(t))
            .Select(t => t.Trim())
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToHashSet(StringComparer.OrdinalIgnoreCase);

        // Mevcut tag'leri isme göre indexle
        var existingTagsByName = post.Tags.ToDictionary(t => t.Name, StringComparer.OrdinalIgnoreCase);

        // Silinecek tag'ler (eski listede var, yeni listede yok)
        var tagsToRemove = post.Tags
            .Where(t => !normalizedTagNames.Contains(t.Name))
            .ToList();
        foreach (var tag in tagsToRemove)
        {
            post.Tags.Remove(tag);
        }

        // Eklenecek tag'ler (yeni listede var, eski listede yok)
        var missingTagNames = normalizedTagNames
            .Where(name => !existingTagsByName.ContainsKey(name))
            .ToList();

        if (missingTagNames.Count > 0)
        {
            // Yeni tag'leri getir veya oluştur
            var newTags = await tagService.GetOrCreateTagsAsync(missingTagNames, cancellationToken);

            // Yeni tag'leri ekle
            // Not: EF Core tracking çatışmasını önlemek için, yeni tag'ler farklı context'ten gelse bile
            // SaveChanges sırasında doğru ilişkiler kurulacak
            foreach (var tag in newTags)
            {
                // Tag zaten collection'da değilse ekle
                if (!post.Tags.Any(t => t.Id == tag.Id))
                {
                    post.Tags.Add(tag);
                }
            }
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
        post.Title = htmlSanitizer.Sanitize(dto.Title) ?? string.Empty;
        // Content is raw markdown rendered by react-markdown (auto-escapes HTML, no rehype-raw)
        // so HTML sanitization is skipped to prevent corruption of code blocks with angle brackets
        post.Content = dto.Content ?? string.Empty;
        post.Excerpt = htmlSanitizer.Sanitize(dto.Excerpt);
        post.FeaturedImageUrl = dto.FeaturedImageUrl;
        post.CategoryId = categoryId;
        // MetaTitle max 70 karakter limiti
        post.MetaTitle = dto.MetaTitle != null && dto.MetaTitle.Length <= 70
            ? htmlSanitizer.Sanitize(dto.MetaTitle)
            : ((dto.Title?.Length ?? 0) <= 70 ? htmlSanitizer.Sanitize(dto.Title) : htmlSanitizer.Sanitize(dto.Title)?[..70]);
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
        catch (DbUpdateConcurrencyException ex)
        {
            throw new ConflictException(PostBusinessRuleMessages.PostModifiedConcurrently, ex);
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



