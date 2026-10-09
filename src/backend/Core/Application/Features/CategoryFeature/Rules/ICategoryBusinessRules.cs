using BlogApp.Core.Application.Common.Models;

namespace BlogApp.Core.Application.Features.CategoryFeature.Rules;

public interface ICategoryBusinessRules
{
    // ============== EXISTENCE & UNIQUENESS ==============
    Task<Result> CheckCategoryExistsAsync(Guid categoryId);
    Task<Result> CheckCategoryNameIsUniqueAsync(string name);
    Task<Result> CheckCategoryNameIsUniqueExceptCurrentAsync(string name, Guid currentId);

    // ============== DELETE VALIDATION ==============
    Task<Result> CheckCategoryCanBeDeletedAsync(Guid categoryId);
}

