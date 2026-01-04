using BlogApp.Server.Application.Common.BusinessRuleEngine;
using BlogApp.Server.Application.Common.Interfaces.Persistence;
using BlogApp.Server.Application.Common.Interfaces.Services;
using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.Features.CategoryFeature.Constants;
using BlogApp.Server.Application.Features.CategoryFeature.Rules;
using BlogApp.Server.Domain.ValueObjects;
using MediatR;

namespace BlogApp.Server.Application.Features.CategoryFeature.Commands.UpdateCategoryCommand;

public class UpdateCategoryCommandHandler(
    IUnitOfWork unitOfWork,
    ICategoryBusinessRules categoryBusinessRules,
    ICacheService cacheService) : IRequestHandler<UpdateCategoryCommandRequest, UpdateCategoryCommandResponse>
{
    public async Task<UpdateCategoryCommandResponse> Handle(UpdateCategoryCommandRequest request, CancellationToken cancellationToken)
    {
        var dto = request.UpdateCategoryCommandRequestDto!;

        // Business Rules
        var ruleResult = await BusinessRuleEngine.RunAsync(
            async () => await categoryBusinessRules.CheckCategoryExistsAsync(dto.Id),
            async () => await categoryBusinessRules.CheckCategoryNameIsUniqueExceptCurrentAsync(dto.Name, dto.Id)
        );

        if (!ruleResult.IsSuccess)
        {
            return new UpdateCategoryCommandResponse
            {
                Result = Result.Failure(ruleResult.Error!)
            };
        }

        var category = await unitOfWork.CategoriesRead.GetByIdAsync(dto.Id, cancellationToken);
        if (category is null)
        {
            return new UpdateCategoryCommandResponse
            {
                Result = Result.Failure(CategoryBusinessRuleMessages.CategoryNotFoundGeneric)
            };
        }

        var slug = Slug.CreateFromTitle(dto.Name);

        category.Name = dto.Name;
        category.Slug = slug.Value;
        category.Description = dto.Description;
        category.ImageUrl = dto.ImageUrl;
        category.DisplayOrder = dto.DisplayOrder;
        category.UpdatedAt = DateTime.UtcNow;

        await unitOfWork.CategoriesWrite.UpdateAsync(category, cancellationToken);
        await unitOfWork.SaveChangesAsync(cancellationToken);

        // Invalidate categories cache
        await cacheService.RotateGroupVersionAsync(CategoryCacheKeys.ListGroup, cancellationToken);

        return new UpdateCategoryCommandResponse
        {
            Result = Result.Success()
        };
    }
}



