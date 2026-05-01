using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.Features.PostFeature.DTOs;
using MediatR;

namespace BlogApp.Server.Application.Features.PostFeature.Queries.GetMyPostsQuery;

public class GetMyPostsQueryRequest : IRequest<Result<PaginatedList<PostListQueryDto>>>
{
    public Guid UserId { get; init; }
    public int PageNumber { get; init; } = 1;
    public int PageSize { get; init; } = 10;
}

