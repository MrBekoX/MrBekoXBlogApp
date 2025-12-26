using BlogApp.Server.Application.DTOs.Posts;
using MediatR;

namespace BlogApp.Server.Application.Features.Posts.Queries.GetPostById;

/// <summary>
/// ID ile post getirme sorgusu
/// </summary>
public record GetPostByIdQuery(Guid Id) : IRequest<PostDetailDto?>;
