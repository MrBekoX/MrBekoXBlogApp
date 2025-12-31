using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.Features.PostFeature.DTOs;

namespace BlogApp.Server.Application.Features.PostFeature.Queries.GetPostBySlugQuery;

public class GetPostBySlugQueryResponse
{
    public Result<PostDetailQueryDto> Result { get; set; } = null!;
}

