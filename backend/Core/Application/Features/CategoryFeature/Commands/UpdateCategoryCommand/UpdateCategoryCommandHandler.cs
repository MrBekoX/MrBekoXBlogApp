using BlogApp.Core.Application.Common.BusinessRuleEngine;
using BlogApp.Core.Application.Common.Errors;
using BlogApp.Core.Application.Common.Interfaces.Persistence;
using BlogApp.Core.Application.Common.Interfaces.Services;
using BlogApp.Core.Application.Common.Models;
using BlogApp.Core.Application.Features.CategoryFeature.Constants;
using BlogApp.Core.Application.Features.CategoryFeature.Rules;
using BlogApp.Core.Domain.ValueObjects;
using MediatR;

namespace BlogApp.Core.Application.Features.CategoryFeature.Commands.UpdateCategoryCommand;

public class UpdateCategoryCommandHandler(
    IUnitOfWork unitOfWork,
    ICategoryBusinessRules categoryBusinessRules,
    ICacheService cacheService) : IRequestHandler<UpdateCategoryCommandRequest, Result<Unit>>
{
    public async Task<Result<Unit>> Handle(UpdateCategoryCommandRequest request, CancellationToken cancellationToken)
    {
        var dto = request.UpdateCategoryCommandRequestDto!;

        // Business Rules
        var ruleResult = await BusinessRuleEngine.RunAsync(
            async () => await categoryBusinessRules.CheckCategoryExistsAsync(dto.Id),
            async () => await categoryBusinessRules.CheckCategoryNameIsUniqueExceptCurrentAsync(dto.Name, dto.Id)
        );

        if (!ruleResult.IsSuccess)
        {
            return Result<Unit>.Failure(ruleResult.ErrorDetail ?? Error.Domain(ruleResult.Error ?? string.Empty));
        }

        var category = await unitOfWork.CategoriesRead.GetByIdAsync(dto.Id, cancellationToken);
        if (category is null)
        {
            return Result<Unit>.Failure(Error.NotFound(CategoryBusinessRuleMessages.CategoryNotFoundGeneric));
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

        return Result<Unit>.Success(Unit.Value);
    }
}
