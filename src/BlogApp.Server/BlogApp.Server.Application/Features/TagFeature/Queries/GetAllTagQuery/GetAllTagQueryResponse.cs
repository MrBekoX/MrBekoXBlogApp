using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.Features.TagFeature.DTOs;

namespace BlogApp.Server.Application.Features.TagFeature.Queries.GetAllTagQuery;

public class GetAllTagQueryResponse
{
    public Result<IEnumerable<GetAllTagQueryDto>> Result { get; set; } = null!;
}

