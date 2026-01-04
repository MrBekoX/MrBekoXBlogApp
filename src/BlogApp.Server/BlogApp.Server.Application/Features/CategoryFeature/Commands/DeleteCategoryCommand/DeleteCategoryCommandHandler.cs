using BlogApp.Server.Application.Common.BusinessRuleEngine;
using BlogApp.Server.Application.Common.Interfaces.Persistence;
using BlogApp.Server.Application.Common.Interfaces.Services;
using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.Features.CategoryFeature.Constants;
using BlogApp.Server.Application.Features.CategoryFeature.Rules;
using MediatR;

namespace BlogApp.Server.Application.Features.CategoryFeature.Commands.DeleteCategoryCommand;

public class DeleteCategoryCommandHandler(
    IUnitOfWork unitOfWork,
    ICategoryBusinessRules categoryBusinessRules,
    ICacheService cacheService) : IRequestHandler<DeleteCategoryCommandRequest, DeleteCategoryCommandResponse>
{
    public async Task<DeleteCategoryCommandResponse> Handle(DeleteCategoryCommandRequest request, CancellationToken cancellationToken)
    {
        // Business Rules
        var ruleResult = await BusinessRuleEngine.RunAsync(
            async () => await categoryBusinessRules.CheckCategoryCanBeDeletedAsync(request.Id)
        );

        if (!ruleResult.IsSuccess)
        {
            return new DeleteCategoryCommandResponse
            {
                Result = Result.Failure(ruleResult.Error!)
            };
        }

        var category = await unitOfWork.CategoriesRead.GetByIdAsync(request.Id, cancellationToken);
        if (category is null)
        {
            return new DeleteCategoryCommandResponse
            {
                Result = Result.Failure(CategoryBusinessRuleMessages.CategoryNotFoundGeneric)
            };
        }

        // Soft delete
        category.IsDeleted = true;
        category.UpdatedAt = DateTime.UtcNow;

        await unitOfWork.CategoriesWrite.UpdateAsync(category, cancellationToken);
        await unitOfWork.SaveChangesAsync(cancellationToken);

        // Invalidate categories cache
        await cacheService.RotateGroupVersionAsync(CategoryCacheKeys.ListGroup, cancellationToken);

        return new DeleteCategoryCommandResponse
        {
            Result = Result.Success()
        };
    }
}

