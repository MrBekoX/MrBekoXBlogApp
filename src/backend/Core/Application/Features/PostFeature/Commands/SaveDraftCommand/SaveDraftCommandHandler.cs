using BlogApp.Core.Application.Common.Errors;
using BlogApp.Core.Application.Common.Interfaces.Messaging;
using BlogApp.Core.Application.Common.Interfaces.Persistence;
using BlogApp.Core.Application.Common.Interfaces.Services;
using BlogApp.Core.Application.Common.Models;
using BlogApp.Core.Application.Features.PostFeature.Constants;
using BlogApp.Core.Domain.Entities;
using BlogApp.Core.Domain.Enums;
using BlogApp.Core.Domain.Exceptions;
using BlogApp.Core.Domain.ValueObjects;
using FluentValidation;
using MediatR;
using Microsoft.EntityFrameworkCore;

namespace BlogApp.Core.Application.Features.PostFeature.Commands.SaveDraftCommand;

public class SaveDraftCommandHandler(
    IUnitOfWork unitOfWork,
    ICurrentUserService currentUserService,
    ITagService tagService,
    IHtmlSanitizerService htmlSanitizer,
    IAgentContentEventService contentEvents) : IRequestHandler<SaveDraftCommandRequest, Result<Guid>>
{
    public async Task<Result<Guid>> Handle(SaveDraftCommandRequest request, CancellationToken cancellationToken)
    {
        var userId = currentUserService.UserId;
        if (userId == null)
        {
            return Result<Guid>.Failure(Error.Forbidden(PostBusinessRuleMessages.UserNotAuthenticated));
        }

        // BUG-001 FIX: Null guard for DTO
        if (request.SaveDraftCommandRequestDto == null)
        {
            return Result<Guid>.Failure(Error.Validation(PostValidationMessages.DraftDataRequired));
        }

        var dto = request.SaveDraftCommandRequestDto;

        // İlk kategoriyi al
        Guid? categoryId = dto.CategoryIds.FirstOrDefault();
        if (categoryId == Guid.Empty) categoryId = null;

        BlogPost post;

        // B8: değişim öncesi yayın durumu + içerik özeti; taslak yaşam döngüsü olay üretmez.
        ArticleContentObservation contentBefore;

        if (dto.Id.HasValue)
        {
            // Mevcut taslağı güncelle
            var existingPost = await unitOfWork.PostsRead.GetSingleAsync(p => p.Id == dto.Id.Value && !p.IsDeleted, cancellationToken);

            if (existingPost == null)
            {
                return Result<Guid>.Failure(Error.NotFound(PostBusinessRuleMessages.PostNotFoundGeneric));
            }

            post = existingPost;

            // B8: taslak kaydetme çoğunlukla olay üretmez (taslak taşınmaz); ANCAK kayıt
            // yayımlanmış bir makaleye dokunuyorsa içerik gerçekten değişmiş olabilir.
            contentBefore = contentEvents.Observe(post);

            // Sadece kendi yazısını veya Admin/Editor güncelleyebilir
            var user = await unitOfWork.UsersRead.GetByIdAsync(userId.Value, cancellationToken);
            if (post.AuthorId != userId && user?.Role != UserRole.Admin && user?.Role != UserRole.Editor)
            {
                return Result<Guid>.Failure(Error.Forbidden(PostBusinessRuleMessages.UnauthorizedToEditPost));
            }

            post.Title = htmlSanitizer.Sanitize(dto.Title) ?? string.Empty;
            // Content is raw markdown — skip HTML sanitization to preserve code blocks
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
            post.UpdatedAt = DateTime.UtcNow;

            // Slug'ı güncelle (sadece draft ise)
            if (post.Status == PostStatus.Draft)
            {
                var slugValue = Slug.CreateFromTitle(dto.Title ?? string.Empty).Value;
                var timestamp = DateTime.UtcNow.Ticks.ToString()[^8..];
                var fullSlug = $"{slugValue}-{timestamp}";
                if (fullSlug.Length > 250)
                {
                    var maxBaseLength = 250 - 9;
                    fullSlug = $"{slugValue[..Math.Min(slugValue.Length, maxBaseLength)].TrimEnd('-')}-{timestamp}";
                }
                post.Slug = fullSlug;
            }

            // Okuma süresini hesapla
            post.CalculateReadingTime();

            await unitOfWork.PostsWrite.UpdateAsync(post, cancellationToken);
        }
        else
        {
            // Slug oluştur - benzersiz olması için timestamp ekle
            var slugValue = Slug.CreateFromTitle(dto.Title).Value;
            var timestamp = DateTime.UtcNow.Ticks.ToString()[^8..];
            var fullSlug = $"{slugValue}-{timestamp}";
            if (fullSlug.Length > 250)
            {
                var maxBaseLength = 250 - 9;
                fullSlug = $"{slugValue[..Math.Min(slugValue.Length, maxBaseLength)].TrimEnd('-')}-{timestamp}";
            }

            post = new BlogPost
            {
                Id = Guid.NewGuid(),
                Title = htmlSanitizer.Sanitize(dto.Title) ?? string.Empty,
                Slug = fullSlug,
                // Content is raw markdown — skip HTML sanitization to preserve code blocks
                Content = dto.Content ?? string.Empty,
                Excerpt = htmlSanitizer.Sanitize(dto.Excerpt),
                FeaturedImageUrl = dto.FeaturedImageUrl,
                Status = PostStatus.Draft,
                AuthorId = userId.Value,
                CategoryId = categoryId,
                // MetaTitle max 70 karakter limiti
                MetaTitle = dto.MetaTitle != null && dto.MetaTitle.Length <= 70
                    ? htmlSanitizer.Sanitize(dto.MetaTitle)
                    : ((dto.Title?.Length ?? 0) <= 70 ? htmlSanitizer.Sanitize(dto.Title) : htmlSanitizer.Sanitize(dto.Title)?[..70]),
                MetaDescription = htmlSanitizer.Sanitize(dto.MetaDescription),
                MetaKeywords = htmlSanitizer.Sanitize(dto.MetaKeywords),
                CreatedAt = DateTime.UtcNow,
                IsDeleted = false
            };

            post.CalculateReadingTime();

            contentBefore = contentEvents.Observe(post);

            await unitOfWork.PostsWrite.AddAsync(post, cancellationToken);
        }

        // Tag'leri al veya oluştur (batch query ile N+1 önleme)
        post.Tags.Clear();
        if (dto.TagNames.Any())
        {
            var tags = await tagService.GetOrCreateTagsAsync(dto.TagNames, cancellationToken);
            foreach (var tag in tags)
            {
                post.Tags.Add(tag);
            }
        }

        try
        {
            // B8: gerekiyorsa revision artışı + içerik olayı AYNI SaveChanges transaction'ında.
            await contentEvents.RecordChangeAsync(post, contentBefore, cancellationToken);
            await unitOfWork.SaveChangesAsync(cancellationToken);
        }
        catch (DbUpdateConcurrencyException)
        {
            return Result<Guid>.Failure(Error.Conflict(PostBusinessRuleMessages.PostModifiedConcurrently));
        }

        return Result<Guid>.Success(post.Id);
    }
}



