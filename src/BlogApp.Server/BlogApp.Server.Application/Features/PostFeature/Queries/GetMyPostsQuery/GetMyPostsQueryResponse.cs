using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.Features.PostFeature.DTOs;

namespace BlogApp.Server.Application.Features.PostFeature.Queries.GetMyPostsQuery;

public class GetMyPostsQueryResponse
{
    public PaginatedList<PostListQueryDto> Result { get; set; } = null!;
}
