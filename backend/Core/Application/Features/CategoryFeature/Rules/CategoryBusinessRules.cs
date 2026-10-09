using BlogApp.Core.Application.Common.Interfaces.Persistence;
using BlogApp.Core.Application.Common.Interfaces.Services;
using BlogApp.Core.Application.Common.Models;
using BlogApp.Core.Application.Features.CategoryFeature.Constants;
using BlogApp.Core.Domain.ValueObjects;

namespace BlogApp.Core.Application.Features.CategoryFeature.Rules;

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

        // Check if category has any posts
        var postCount = await _unitOfWork.PostsRead.CountWhereAsync(
            p => p.CategoryId == categoryId && !p.IsDeleted);

        if (postCount > 0)
            return Result.Failure(CategoryBusinessRuleMessages.CannotDeleteCategoryWithPosts(postCount));

        return Result.Success();
    }
}


