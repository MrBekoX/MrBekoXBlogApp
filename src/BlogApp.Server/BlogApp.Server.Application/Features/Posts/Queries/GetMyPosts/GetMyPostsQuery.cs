using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.DTOs.Posts;
using MediatR;

namespace BlogApp.Server.Application.Features.Posts.Queries.GetMyPosts;

/// <summary>
/// Get current user's posts query
/// </summary>
public record GetMyPostsQuery : IRequest<PaginatedList<PostDto>>
{
    public Guid UserId { get; init; }
    public int PageNumber { get; init; } = 1;
    public int PageSize { get; init; } = 10;
}

