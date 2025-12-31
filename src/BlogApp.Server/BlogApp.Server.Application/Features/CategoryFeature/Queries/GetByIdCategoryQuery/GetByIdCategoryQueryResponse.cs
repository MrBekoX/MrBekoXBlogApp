using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.Features.CategoryFeature.DTOs;

namespace BlogApp.Server.Application.Features.CategoryFeature.Queries.GetByIdCategoryQuery;

public class GetByIdCategoryQueryResponse
{
    public Result<GetByIdCategoryQueryDto> Result { get; set; } = null!;
}

