using BlogApp.Server.Application.Common.Interfaces;
using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.Features.CategoryFeature.Constants;
using BlogApp.Server.Application.Features.CategoryFeature.DTOs;
using MediatR;

namespace BlogApp.Server.Application.Features.CategoryFeature.Queries.GetByIdCategoryQuery;

public class GetByIdCategoryQueryHandler(
    IUnitOfWork unitOfWork) : IRequestHandler<GetByIdCategoryQueryRequest, GetByIdCategoryQueryResponse>
{
    public async Task<GetByIdCategoryQueryResponse> Handle(GetByIdCategoryQueryRequest request, CancellationToken cancellationToken)
    {
        var category = await unitOfWork.Categories.GetByIdAsync(request.Id, cancellationToken);

        if (category is null || category.IsDeleted)
        {
            return new GetByIdCategoryQueryResponse
            {
                Result = Result<GetByIdCategoryQueryDto>.Failure(CategoryBusinessRuleMessages.CategoryNotFoundGeneric)
            };
        }

        var dto = new GetByIdCategoryQueryDto
        {
            Id = category.Id,
            Name = category.Name,
            Slug = category.Slug,
            Description = category.Description,
            ImageUrl = category.ImageUrl,
            DisplayOrder = category.DisplayOrder,
            IsActive = category.IsActive,
            PostCount = 0,
            CreatedAt = category.CreatedAt,
            UpdatedAt = category.UpdatedAt
        };

        return new GetByIdCategoryQueryResponse
        {
            Result = Result<GetByIdCategoryQueryDto>.Success(dto)
        };
    }
}
