using BlogApp.Core.Application.Common.Models;
using BlogApp.Core.Application.Features.PostFeature.DTOs;
using MediatR;

namespace BlogApp.Core.Application.Features.PostFeature.Queries.GetMyPostsQuery;

public class GetMyPostsQueryRequest : IRequest<Result<PaginatedList<PostListQueryDto>>>
{
    public Guid UserId { get; init; }
    public int PageNumber { get; init; } = 1;
    public int PageSize { get; init; } = 10;
}

