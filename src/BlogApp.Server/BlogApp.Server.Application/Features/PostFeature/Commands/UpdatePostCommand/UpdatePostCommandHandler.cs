using BlogApp.Server.Application.Common.BusinessRuleEngine;
using BlogApp.Server.Application.Common.Interfaces;
using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.Features.PostFeature.Constants;
using BlogApp.Server.Application.Features.PostFeature.Rules;
using BlogApp.Server.Domain.Entities;
using BlogApp.Server.Domain.Enums;
using BlogApp.Server.Domain.ValueObjects;
using MediatR;

namespace BlogApp.Server.Application.Features.PostFeature.Commands.UpdatePostCommand;

public class UpdatePostCommandHandler(
    IUnitOfWork unitOfWork,
    ICurrentUserService currentUserService,
    IPostBusinessRules postBusinessRules) : IRequestHandler<UpdatePostCommandRequest, UpdatePostCommandResponse>
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

        var post = await unitOfWork.Posts.GetByIdAsync(dto.Id, cancellationToken);
        if (post is null)
        {
            return new UpdatePostCommandResponse
            {
                Result = Result.Failure(PostBusinessRuleMessages.PostNotFoundGeneric)
            };
        }

        // Başlık değiştiyse slug güncelle
        if (post.Title != dto.Title)
        {
            var newSlug = Slug.CreateFromTitle(dto.Title);
            var existingPost = await unitOfWork.Posts.GetAsync(
                p => p.Slug == newSlug.Value && p.Id != dto.Id, cancellationToken);

            post.Slug = existingPost is not null
                ? $"{newSlug.Value}-{Guid.NewGuid().ToString()[..8]}"
                : newSlug.Value;
        }

        // Tag'leri al veya oluştur
        post.Tags.Clear();
        if (dto.TagNames.Any())
        {
            foreach (var tagName in dto.TagNames)
            {
                var existingTag = await unitOfWork.Tags.GetAsync(t => t.Name == tagName, cancellationToken);
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
                    await unitOfWork.Tags.AddAsync(newTag, cancellationToken);
                    post.Tags.Add(newTag);
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
        post.Title = dto.Title;
        post.Content = dto.Content;
        post.Excerpt = dto.Excerpt;
        post.FeaturedImageUrl = dto.FeaturedImageUrl;
        post.CategoryId = categoryId;
        post.MetaTitle = dto.MetaTitle ?? dto.Title;
        post.MetaDescription = dto.MetaDescription;
        post.MetaKeywords = dto.MetaKeywords;
        post.IsFeatured = dto.IsFeatured;
        post.Status = status;
        post.UpdatedAt = DateTime.UtcNow;
        post.UpdatedBy = currentUserService.UserName;

        // Yayınlanma tarihi kontrolü
        if (status == PostStatus.Published && post.PublishedAt == null)
        {
            post.PublishedAt = DateTime.UtcNow;
        }

        // Okuma süresini yeniden hesapla
        post.CalculateReadingTime();

        unitOfWork.Posts.Update(post);
        await unitOfWork.SaveChangesAsync(cancellationToken);

        return new UpdatePostCommandResponse
        {
            Result = Result.Success()
        };
    }
}
