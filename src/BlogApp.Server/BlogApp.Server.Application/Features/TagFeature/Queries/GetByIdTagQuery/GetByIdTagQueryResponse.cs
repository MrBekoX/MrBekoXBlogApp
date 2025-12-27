using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.Features.TagFeature.DTOs;

namespace BlogApp.Server.Application.Features.TagFeature.Queries.GetByIdTagQuery;

public class GetByIdTagQueryResponse
{
    public Result<GetByIdTagQueryDto> Result { get; set; } = null!;
}
