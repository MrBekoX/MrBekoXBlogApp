using BlogApp.Server.Application.DTOs.Posts;
using MediatR;

namespace BlogApp.Server.Application.Features.Posts.Queries.GetPostBySlug;

/// <summary>
/// Slug ile post getirme sorgusu
/// </summary>
public record GetPostBySlugQuery(string Slug, bool IncrementViewCount = true) : IRequest<PostDetailDto?>;
