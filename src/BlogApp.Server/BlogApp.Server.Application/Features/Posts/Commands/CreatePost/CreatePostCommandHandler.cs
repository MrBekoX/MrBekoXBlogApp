using BlogApp.Server.Application.Common.Interfaces;
using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Domain.Entities;
using BlogApp.Server.Domain.Enums;
using BlogApp.Server.Domain.ValueObjects;
using MediatR;

namespace BlogApp.Server.Application.Features.Posts.Commands.CreatePost;

/// <summary>
/// CreatePostCommand handler
/// </summary>
public class CreatePostCommandHandler : IRequestHandler<CreatePostCommand, Result<Guid>>
{
    private readonly IUnitOfWork _unitOfWork;
    private readonly ICurrentUserService _currentUserService;

    public CreatePostCommandHandler(IUnitOfWork unitOfWork, ICurrentUserService currentUserService)
    {
        _unitOfWork = unitOfWork;
        _currentUserService = currentUserService;
    }

    public async Task<Result<Guid>> Handle(CreatePostCommand request, CancellationToken cancellationToken)
    {
        if (_currentUserService.UserId is null)
            return Result<Guid>.Failure("User not authenticated");

        // Slug oluştur - her zaman benzersiz olması için timestamp ekle
        var baseSlug = Slug.CreateFromTitle(request.Title);
        var timestamp = DateTime.UtcNow.Ticks.ToString()[^8..]; // Son 8 karakter
        var slug = Slug.Create($"{baseSlug.Value}-{timestamp}");

        // Tag'leri al veya oluştur
        var tags = new List<Tag>();
        if (request.TagNames.Any())
        {
            foreach (var tagName in request.TagNames)
            {
                var existingTag = await _unitOfWork.Tags.GetAsync(t => t.Name == tagName, cancellationToken);
                if (existingTag is not null)
                {
                    tags.Add(existingTag);
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
                    tags.Add(newTag);
                }
            }
        }

        // İlk kategoriyi al (frontend birden fazla kategori gönderiyor olabilir)
        Guid? categoryId = request.CategoryIds.FirstOrDefault();
        if (categoryId == Guid.Empty) categoryId = null;

        // Status'u parse et
        var status = request.Status switch
        {
            "Published" => PostStatus.Published,
            "Archived" => PostStatus.Archived,
            _ => PostStatus.Draft
        };

        // Post oluştur
        var post = new BlogPost
        {
            Id = Guid.NewGuid(),
            Title = request.Title,
            Slug = slug.Value,
            Content = request.Content,
            Excerpt = request.Excerpt,
            FeaturedImageUrl = request.FeaturedImageUrl,
            CategoryId = categoryId,
            AuthorId = _currentUserService.UserId.Value,
            MetaTitle = request.MetaTitle ?? request.Title,
            MetaDescription = request.MetaDescription,
            MetaKeywords = request.MetaKeywords,
            Status = status,
            PublishedAt = status == PostStatus.Published ? DateTime.UtcNow : null,
            Tags = tags,
            CreatedAt = DateTime.UtcNow,
            CreatedBy = _currentUserService.UserName
        };

        // Okuma süresini hesapla
        post.CalculateReadingTime();

        await _unitOfWork.Posts.AddAsync(post, cancellationToken);
        await _unitOfWork.SaveChangesAsync(cancellationToken);

        return Result<Guid>.Success(post.Id);
    }
}
