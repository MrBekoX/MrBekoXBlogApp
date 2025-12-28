using BlogApp.Server.Application.Common.Interfaces;
using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.Features.PostFeature.Constants;
using BlogApp.Server.Domain.Entities;
using BlogApp.Server.Domain.Enums;
using BlogApp.Server.Domain.ValueObjects;
using MediatR;

namespace BlogApp.Server.Application.Features.PostFeature.Commands.SaveDraftCommand;

public class SaveDraftCommandHandler(
    IUnitOfWork unitOfWork,
    ICurrentUserService currentUserService) : IRequestHandler<SaveDraftCommandRequest, SaveDraftCommandResponse>
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

        var dto = request.SaveDraftCommandRequestDto!;

        // İlk kategoriyi al
        Guid? categoryId = dto.CategoryIds.FirstOrDefault();
        if (categoryId == Guid.Empty) categoryId = null;

        BlogPost post;

        if (dto.Id.HasValue)
        {
            // Mevcut taslağı güncelle
            post = await unitOfWork.PostsRead.GetSingleAsync(p => p.Id == dto.Id.Value && !p.IsDeleted, cancellationToken);

            if (post == null)
            {
                return new SaveDraftCommandResponse
                {
                    Result = Result<Guid>.Failure(PostBusinessRuleMessages.PostNotFoundGeneric)
                };
            }

            // Sadece kendi yazısını veya Admin/Editor güncelleyebilir
            var user = await unitOfWork.UsersRead.GetByIdAsync(userId.Value, cancellationToken);
            if (post.AuthorId != userId && user?.Role != UserRole.Admin && user?.Role != UserRole.Editor)
            {
                return new SaveDraftCommandResponse
                {
                    Result = Result<Guid>.Failure(PostBusinessRuleMessages.UnauthorizedToEditPost)
                };
            }

            post.Title = dto.Title;
            post.Content = dto.Content;
            post.Excerpt = dto.Excerpt;
            post.FeaturedImageUrl = dto.FeaturedImageUrl;
            post.CategoryId = categoryId;
            post.MetaTitle = dto.MetaTitle;
            post.MetaDescription = dto.MetaDescription;
            post.MetaKeywords = dto.MetaKeywords;
            post.UpdatedAt = DateTime.UtcNow;

            // Slug'ı güncelle (sadece draft ise)
            if (post.Status == PostStatus.Draft)
            {
                post.Slug = Slug.Create(dto.Title).Value;
            }

            // Okuma süresini hesapla
            post.CalculateReadingTime();

            await unitOfWork.PostsWrite.UpdateAsync(post, cancellationToken);
        }
        else
        {
            // Yeni taslak oluştur
            post = new BlogPost
            {
                Id = Guid.NewGuid(),
                Title = dto.Title,
                Slug = Slug.Create(dto.Title).Value,
                Content = dto.Content,
                Excerpt = dto.Excerpt,
                FeaturedImageUrl = dto.FeaturedImageUrl,
                Status = PostStatus.Draft,
                AuthorId = userId.Value,
                CategoryId = categoryId,
                MetaTitle = dto.MetaTitle,
                MetaDescription = dto.MetaDescription,
                MetaKeywords = dto.MetaKeywords,
                CreatedAt = DateTime.UtcNow,
                IsDeleted = false
            };

            post.CalculateReadingTime();

            await unitOfWork.PostsWrite.AddAsync(post, cancellationToken);
        }

        // Tag'leri al veya oluştur
        if (dto.TagNames.Any())
        {
            post.Tags.Clear();
            foreach (var tagName in dto.TagNames)
            {
                var existingTag = await unitOfWork.TagsRead.GetSingleAsync(t => t.Name == tagName, cancellationToken);
                if (existingTag is not null)
                {
                    post.Tags.Add(existingTag);
                }
                else
                {
                    var newTag = new Tag
                    {
                        Id = Guid.NewGuid(),
                        Name = tagName,
                        Slug = Slug.CreateFromTitle(tagName).Value,
                        CreatedAt = DateTime.UtcNow
                    };
                    await unitOfWork.TagsWrite.AddAsync(newTag, cancellationToken);
                    post.Tags.Add(newTag);
                }
            }
        }

        await unitOfWork.SaveChangesAsync(cancellationToken);

        return new SaveDraftCommandResponse
        {
            Result = Result<Guid>.Success(post.Id)
        };
    }
}
