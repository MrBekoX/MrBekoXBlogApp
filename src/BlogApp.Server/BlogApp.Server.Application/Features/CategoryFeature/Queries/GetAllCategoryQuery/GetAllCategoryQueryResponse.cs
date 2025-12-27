using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.Features.CategoryFeature.DTOs;

namespace BlogApp.Server.Application.Features.CategoryFeature.Queries.GetAllCategoryQuery;

public class GetAllCategoryQueryResponse
{
    public Result<IEnumerable<GetAllCategoryQueryDto>> Result { get; set; } = null!;
}
