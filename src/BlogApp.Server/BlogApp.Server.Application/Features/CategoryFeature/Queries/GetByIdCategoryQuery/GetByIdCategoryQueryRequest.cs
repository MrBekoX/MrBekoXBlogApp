using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.Features.CategoryFeature.DTOs;
using MediatR;

namespace BlogApp.Server.Application.Features.CategoryFeature.Queries.GetByIdCategoryQuery;

public class GetByIdCategoryQueryRequest : IRequest<Result<GetByIdCategoryQueryDto>>
{
    public Guid Id { get; set; }
}
