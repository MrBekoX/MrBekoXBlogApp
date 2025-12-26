using BlogApp.Server.Application.Common.Models;
using MediatR;

namespace BlogApp.Server.Application.Features.Posts.Commands.SaveDraft;

/// <summary>
/// Taslak kaydetme komutu (auto-save için)
/// </summary>
public record SaveDraftCommand : IRequest<Result<Guid>>
{
    /// <summary>
    /// Post ID (null ise yeni taslak oluşturulur)
    /// </summary>
    public Guid? Id { get; init; }
    
    public string Title { get; init; } = default!;
    public string Content { get; init; } = default!;
    public string? Excerpt { get; init; }
    public string? FeaturedImageUrl { get; init; }
    public List<Guid> CategoryIds { get; init; } = new();
    public List<string> TagNames { get; init; } = new();
    public string? MetaTitle { get; init; }
    public string? MetaDescription { get; init; }
    public string? MetaKeywords { get; init; }
}

