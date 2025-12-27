using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.Features.PostFeature.DTOs;

namespace BlogApp.Server.Application.Features.PostFeature.Queries.GetPostByIdQuery;

public class GetPostByIdQueryResponse
{
    public Result<PostDetailQueryDto> Result { get; set; } = null!;
}
