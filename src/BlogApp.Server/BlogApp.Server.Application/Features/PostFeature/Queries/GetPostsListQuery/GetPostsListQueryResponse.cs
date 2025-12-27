using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.Features.PostFeature.DTOs;

namespace BlogApp.Server.Application.Features.PostFeature.Queries.GetPostsListQuery;

public class GetPostsListQueryResponse
{
    public PaginatedList<PostListQueryDto> Result { get; set; } = null!;
}
