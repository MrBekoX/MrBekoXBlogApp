using BlogApp.Server.Application.Common.Interfaces;
using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Domain.Entities;
using BlogApp.Server.Domain.Enums;
using BlogApp.Server.Domain.Exceptions;
using BlogApp.Server.Domain.ValueObjects;
using MediatR;

namespace BlogApp.Server.Application.Features.Posts.Commands.UpdatePost;

/// <summary>
/// UpdatePostCommand handler
/// </summary>
public class UpdatePostCommandHandler : IRequestHandler<UpdatePostCommand, Result>
{
    private readonly IUnitOfWork _unitOfWork;
    private readonly ICurrentUserService _currentUserService;

    public UpdatePostCommandHandler(IUnitOfWork unitOfWork, ICurrentUserService currentUserService)
    {
        _unitOfWork = unitOfWork;
        _currentUserService = currentUserService;
    }

    public async Task<Result> Handle(UpdatePostCommand request, CancellationToken cancellationToken)
    {
        var post = await _unitOfWork.Posts.GetByIdAsync(request.Id, cancellationToken);
        if (post is null)
            throw new NotFoundException(nameof(post), request.Id);

        // Başlık değiştiyse slug güncelle
        if (post.Title != request.Title)
        {
            var newSlug = Slug.CreateFromTitle(request.Title);
            var existingPost = await _unitOfWork.Posts.GetAsync(
                p => p.Slug == newSlug.Value && p.Id != request.Id, cancellationToken);

            post.Slug = existingPost is not null
                ? $"{newSlug.Value}-{Guid.NewGuid().ToString()[..8]}"
                : newSlug.Value;
        }

        // Tag'leri al veya oluştur
        post.Tags.Clear();
        if (request.TagNames.Any())
        {
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

        // İlk kategoriyi al
        Guid? categoryId = request.CategoryIds.FirstOrDefault();
        if (categoryId == Guid.Empty) categoryId = null;

        // Status'u parse et
        var status = request.Status switch
        {
            "Published" => PostStatus.Published,
            "Archived" => PostStatus.Archived,
            _ => PostStatus.Draft
        };

        // Diğer alanları güncelle
        post.Title = request.Title;
        post.Content = request.Content;
        post.Excerpt = request.Excerpt;
        post.FeaturedImageUrl = request.FeaturedImageUrl;
        post.CategoryId = categoryId;
        post.MetaTitle = request.MetaTitle ?? request.Title;
        post.MetaDescription = request.MetaDescription;
        post.MetaKeywords = request.MetaKeywords;
        post.IsFeatured = request.IsFeatured;
        post.Status = status;
        post.UpdatedAt = DateTime.UtcNow;
        post.UpdatedBy = _currentUserService.UserName;

        // Yayınlanma tarihi kontrolü
        if (status == PostStatus.Published && post.PublishedAt == null)
        {
            post.PublishedAt = DateTime.UtcNow;
        }

        // Okuma süresini yeniden hesapla
        post.CalculateReadingTime();

        _unitOfWork.Posts.Update(post);
        await _unitOfWork.SaveChangesAsync(cancellationToken);

        return Result.Success();
    }
}
