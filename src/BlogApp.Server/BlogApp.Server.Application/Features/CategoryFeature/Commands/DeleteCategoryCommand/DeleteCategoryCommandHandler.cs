using BlogApp.Server.Application.Common.BusinessRuleEngine;
using BlogApp.Server.Application.Common.Errors;
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
    ICacheService cacheService) : IRequestHandler<DeleteCategoryCommandRequest, Result<Unit>>
{
    public async Task<Result<Unit>> Handle(DeleteCategoryCommandRequest request, CancellationToken cancellationToken)
    {
        // Business Rules
        var ruleResult = await BusinessRuleEngine.RunAsync(
            async () => await categoryBusinessRules.CheckCategoryCanBeDeletedAsync(request.Id)
        );

        if (!ruleResult.IsSuccess)
        {
            return Result<Unit>.Failure(ruleResult.ErrorDetail ?? Error.Domain(ruleResult.Error ?? string.Empty));
        }

        var category = await unitOfWork.CategoriesRead.GetByIdAsync(request.Id, cancellationToken);
        if (category is null)
        {
            return Result<Unit>.Failure(Error.NotFound(CategoryBusinessRuleMessages.CategoryNotFoundGeneric));
        }

        // Soft delete
        category.IsDeleted = true;
        category.UpdatedAt = DateTime.UtcNow;

        await unitOfWork.CategoriesWrite.UpdateAsync(category, cancellationToken);
        await unitOfWork.SaveChangesAsync(cancellationToken);

        // Invalidate categories cache
        await cacheService.RotateGroupVersionAsync(CategoryCacheKeys.ListGroup, cancellationToken);

        return Result<Unit>.Success(Unit.Value);
    }
}
