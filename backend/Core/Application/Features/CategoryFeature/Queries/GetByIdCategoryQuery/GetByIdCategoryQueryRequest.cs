using BlogApp.Core.Application.Common.Models;
using BlogApp.Core.Application.Features.CategoryFeature.DTOs;
using MediatR;

namespace BlogApp.Core.Application.Features.CategoryFeature.Queries.GetByIdCategoryQuery;

public class GetByIdCategoryQueryRequest : IRequest<Result<GetByIdCategoryQueryDto>>
{
    public Guid Id { get; set; }
}
