using BlogApp.Server.Application.Common.Interfaces;
using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Domain.Entities;
using BlogApp.Server.Domain.Enums;
using BlogApp.Server.Domain.ValueObjects;
using MediatR;

namespace BlogApp.Server.Application.Features.Posts.Commands.SaveDraft;

/// <summary>
/// Taslak kaydetme handler (auto-save için)
/// </summary>
public class SaveDraftCommandHandler : IRequestHandler<SaveDraftCommand, Result<Guid>>
{
    private readonly IUnitOfWork _unitOfWork;
    private readonly ICurrentUserService _currentUserService;

    public SaveDraftCommandHandler(IUnitOfWork unitOfWork, ICurrentUserService currentUserService)
    {
        _unitOfWork = unitOfWork;
        _currentUserService = currentUserService;
    }

    public async Task<Result<Guid>> Handle(SaveDraftCommand request, CancellationToken cancellationToken)
    {
        var userId = _currentUserService.UserId;
        if (userId == null)
            return Result<Guid>.Failure("User not authenticated");

        // İlk kategoriyi al
        Guid? categoryId = request.CategoryIds.FirstOrDefault();
        if (categoryId == Guid.Empty) categoryId = null;

        BlogPost post;

        if (request.Id.HasValue)
        {
            // Mevcut taslağı güncelle
            post = await _unitOfWork.Posts.GetByIdAsync(request.Id.Value, cancellationToken);
            
            if (post == null)
                return Result<Guid>.Failure("Post not found");

            // Sadece kendi yazısını veya Admin/Editor güncelleyebilir
            var user = await _unitOfWork.Users.GetByIdAsync(userId.Value, cancellationToken);
            if (post.AuthorId != userId && user?.Role != UserRole.Admin && user?.Role != UserRole.Editor)
                return Result<Guid>.Failure("Not authorized to edit this post");

            post.Title = request.Title;
            post.Content = request.Content;
            post.Excerpt = request.Excerpt;
            post.FeaturedImageUrl = request.FeaturedImageUrl;
            post.CategoryId = categoryId;
            post.MetaTitle = request.MetaTitle;
            post.MetaDescription = request.MetaDescription;
            post.MetaKeywords = request.MetaKeywords;
            post.UpdatedAt = DateTime.UtcNow;
            
            // Slug'ı güncelle (sadece draft ise)
            if (post.Status == PostStatus.Draft)
            {
                post.Slug = Slug.Create(request.Title).Value;
            }
            
            // Okuma süresini hesapla
            post.CalculateReadingTime();

            _unitOfWork.Posts.Update(post);
        }
        else
        {
            // Yeni taslak oluştur
            post = new BlogPost
            {
                Id = Guid.NewGuid(),
                Title = request.Title,
                Slug = Slug.Create(request.Title).Value,
                Content = request.Content,
                Excerpt = request.Excerpt,
                FeaturedImageUrl = request.FeaturedImageUrl,
                Status = PostStatus.Draft,
                AuthorId = userId.Value,
                CategoryId = categoryId,
                MetaTitle = request.MetaTitle,
                MetaDescription = request.MetaDescription,
                MetaKeywords = request.MetaKeywords,
                CreatedAt = DateTime.UtcNow,
                IsDeleted = false
            };
            
            post.CalculateReadingTime();
            
            await _unitOfWork.Posts.AddAsync(post, cancellationToken);
        }

        // Tag'leri al veya oluştur
        if (request.TagNames.Any())
        {
            post.Tags.Clear();
            foreach (var tagName in request.TagNames)
            {
                var existingTag = await _unitOfWork.Tags.GetAsync(t => t.Name == tagName, cancellationToken);
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
                    await _unitOfWork.Tags.AddAsync(newTag, cancellationToken);
                    post.Tags.Add(newTag);
                }
            }
        }

        await _unitOfWork.SaveChangesAsync(cancellationToken);

        return Result<Guid>.Success(post.Id);
    }
}

