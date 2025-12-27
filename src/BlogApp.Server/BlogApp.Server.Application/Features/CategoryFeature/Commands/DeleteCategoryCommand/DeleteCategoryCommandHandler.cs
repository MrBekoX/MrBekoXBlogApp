using BlogApp.Server.Application.Common.BusinessRuleEngine;
using BlogApp.Server.Application.Common.Interfaces;
using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.Features.CategoryFeature.Constants;
using BlogApp.Server.Application.Features.CategoryFeature.Rules;
using MediatR;

namespace BlogApp.Server.Application.Features.CategoryFeature.Commands.DeleteCategoryCommand;

public class DeleteCategoryCommandHandler(
    IUnitOfWork unitOfWork,
    ICategoryBusinessRules categoryBusinessRules) : IRequestHandler<DeleteCategoryCommandRequest, DeleteCategoryCommandResponse>
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

        var category = await unitOfWork.Categories.GetByIdAsync(request.Id, cancellationToken);
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

        unitOfWork.Categories.Update(category);
        await unitOfWork.SaveChangesAsync(cancellationToken);

        return new DeleteCategoryCommandResponse
        {
            Result = Result.Success()
        };
    }
}
