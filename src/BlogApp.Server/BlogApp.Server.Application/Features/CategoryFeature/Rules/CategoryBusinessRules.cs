using BlogApp.Server.Application.Common.Interfaces;
using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.Features.CategoryFeature.Constants;
using BlogApp.Server.Domain.ValueObjects;

namespace BlogApp.Server.Application.Features.CategoryFeature.Rules;

public class CategoryBusinessRules : ICategoryBusinessRules
{
    private readonly IUnitOfWork _unitOfWork;

    public CategoryBusinessRules(IUnitOfWork unitOfWork)
    {
        _unitOfWork = unitOfWork;
    }

    // ============== EXISTENCE & UNIQUENESS ==============

    public async Task<Result> CheckCategoryExistsAsync(Guid categoryId)
    {
        var category = await _unitOfWork.CategoriesRead.GetByIdAsync(categoryId);

        return category is not null && !category.IsDeleted
            ? Result.Success()
            : Result.Failure(CategoryBusinessRuleMessages.CategoryNotFound(categoryId));
    }

    public async Task<Result> CheckCategoryNameIsUniqueAsync(string name)
    {
        var slug = Slug.CreateFromTitle(name);
        var existingCategory = await _unitOfWork.CategoriesRead.GetSingleAsync(
            c => c.Slug == slug.Value && !c.IsDeleted);

        return existingCategory is null
            ? Result.Success()
            : Result.Failure(CategoryBusinessRuleMessages.CategoryNameAlreadyExists(name));
    }

    public async Task<Result> CheckCategoryNameIsUniqueExceptCurrentAsync(string name, Guid currentId)
    {
        var slug = Slug.CreateFromTitle(name);
        var existingCategory = await _unitOfWork.CategoriesRead.GetSingleAsync(
            c => c.Slug == slug.Value && c.Id != currentId && !c.IsDeleted);

        return existingCategory is null
            ? Result.Success()
            : Result.Failure(CategoryBusinessRuleMessages.CategoryNameAlreadyExists(name));
    }

    // ============== DELETE VALIDATION ==============

    public async Task<Result> CheckCategoryCanBeDeletedAsync(Guid categoryId)
    {
        var existsResult = await CheckCategoryExistsAsync(categoryId);
        if (!existsResult.IsSuccess)
            return existsResult;

        return Result.Success();
    }
}