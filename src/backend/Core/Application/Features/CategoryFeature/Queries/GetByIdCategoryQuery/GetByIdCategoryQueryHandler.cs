using BlogApp.Core.Application.Common.Errors;
using BlogApp.Core.Application.Common.Interfaces.Persistence;
using BlogApp.Core.Application.Common.Models;
using BlogApp.Core.Application.Features.CategoryFeature.Constants;
using BlogApp.Core.Application.Features.CategoryFeature.DTOs;
using MediatR;

namespace BlogApp.Core.Application.Features.CategoryFeature.Queries.GetByIdCategoryQuery;

public class GetByIdCategoryQueryHandler(
    IUnitOfWork unitOfWork) : IRequestHandler<GetByIdCategoryQueryRequest, Result<GetByIdCategoryQueryDto>>
{
    public async Task<Result<GetByIdCategoryQueryDto>> Handle(GetByIdCategoryQueryRequest request, CancellationToken cancellationToken)
    {
        var category = await unitOfWork.CategoriesRead.GetByIdAsync(request.Id, cancellationToken);

        if (category is null)
        {
            return Result<GetByIdCategoryQueryDto>.Failure(Error.NotFound(CategoryBusinessRuleMessages.CategoryNotFound(request.Id)));
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

        return Result<GetByIdCategoryQueryDto>.Success(dto);
    }
}
