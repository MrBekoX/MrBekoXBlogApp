using BlogApp.Server.Application.Common.Interfaces.Persistence;
using BlogApp.Server.Application.Common.Interfaces.Services;
using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.Features.PostFeature.Constants;
using BlogApp.Server.Domain.Entities;
using BlogApp.Server.Domain.Enums;
using BlogApp.Server.Domain.ValueObjects;
using FluentValidation;
using MediatR;

namespace BlogApp.Server.Application.Features.PostFeature.Commands.SaveDraftCommand;

public class SaveDraftCommandHandler(
    IUnitOfWork unitOfWork,
    ICurrentUserService currentUserService,
    ITagService tagService,
    IHtmlSanitizerService htmlSanitizer) : IRequestHandler<SaveDraftCommandRequest, SaveDraftCommandResponse>
{
    public async Task<SaveDraftCommandResponse> Handle(SaveDraftCommandRequest request, CancellationToken cancellationToken)
    {
        var userId = currentUserService.UserId;
        if (userId == null)
        {
            return new SaveDraftCommandResponse
            {
                Result = Result<Guid>.Failure(PostBusinessRuleMessages.UserNotAuthenticated)
            };
        }

        // BUG-001 FIX: Null guard for DTO
        if (request.SaveDraftCommandRequestDto == null)
        {
            return new SaveDraftCommandResponse
            {
                Result = Result<Guid>.Failure(PostValidationMessages.DraftDataRequired)
            };
        }

        var dto = request.SaveDraftCommandRequestDto;

        // İlk kategoriyi al
        Guid? categoryId = dto.CategoryIds.FirstOrDefault();
        if (categoryId == Guid.Empty) categoryId = null;

        BlogPost post;

        if (dto.Id.HasValue)
        {
            // Mevcut taslağı güncelle
            var existingPost = await unitOfWork.PostsRead.GetSingleAsync(p => p.Id == dto.Id.Value && !p.IsDeleted, cancellationToken);

            if (existingPost == null)
            {
                return new SaveDraftCommandResponse
                {
                    Result = Result<Guid>.Failure(PostBusinessRuleMessages.PostNotFoundGeneric)
                };
            }

            post = existingPost;

            // Sadece kendi yazısını veya Admin/Editor güncelleyebilir
            var user = await unitOfWork.UsersRead.GetByIdAsync(userId.Value, cancellationToken);
            if (post.AuthorId != userId && user?.Role != UserRole.Admin && user?.Role != UserRole.Editor)
            {
                return new SaveDraftCommandResponse
                {
                    Result = Result<Guid>.Failure(PostBusinessRuleMessages.UnauthorizedToEditPost)
                };
            }

            // BUG-006 FIX: HTML sanitization for all user inputs
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
            post.UpdatedAt = DateTime.UtcNow;

            // Slug'ı güncelle (sadece draft ise)
            if (post.Status == PostStatus.Draft)
            {
                var slugValue = Slug.CreateFromTitle(dto.Title).Value;
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

            // Yeni taslak oluştur - BUG-006 FIX: HTML sanitization
            post = new BlogPost
            {
                Id = Guid.NewGuid(),
                Title = htmlSanitizer.Sanitize(dto.Title),
                Slug = fullSlug,
                Content = htmlSanitizer.Sanitize(dto.Content),
                Excerpt = htmlSanitizer.Sanitize(dto.Excerpt),
                FeaturedImageUrl = dto.FeaturedImageUrl,
                Status = PostStatus.Draft,
                AuthorId = userId.Value,
                CategoryId = categoryId,
                // MetaTitle max 70 karakter limiti
                MetaTitle = dto.MetaTitle != null && dto.MetaTitle.Length <= 70
                    ? htmlSanitizer.Sanitize(dto.MetaTitle)
                    : (dto.Title.Length <= 70 ? htmlSanitizer.Sanitize(dto.Title) : htmlSanitizer.Sanitize(dto.Title)[..70]),
                MetaDescription = htmlSanitizer.Sanitize(dto.MetaDescription),
                MetaKeywords = htmlSanitizer.Sanitize(dto.MetaKeywords),
                CreatedAt = DateTime.UtcNow,
                IsDeleted = false
            };

            post.CalculateReadingTime();

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

        await unitOfWork.SaveChangesAsync(cancellationToken);

        return new SaveDraftCommandResponse
        {
            Result = Result<Guid>.Success(post.Id)
        };
    }
}



