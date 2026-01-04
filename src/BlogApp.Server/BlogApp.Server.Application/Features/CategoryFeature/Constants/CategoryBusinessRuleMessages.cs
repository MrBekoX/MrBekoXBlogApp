namespace BlogApp.Server.Application.Features.CategoryFeature.Constants;

public static class CategoryBusinessRuleMessages
{
    // Existence Messages
    public static string CategoryNotFound(Guid categoryId)
        => $"Category with id '{categoryId}' not found";

    public const string CategoryNotFoundGeneric = "Category not found";

    // Uniqueness Messages
    public static string CategoryNameAlreadyExists(string name)
        => $"Category with name '{name}' already exists";

    // Delete Validation Messages
    public static string CannotDeleteCategoryWithPosts(int postCount)
        => $"Bu kategori silinemez. Kategoriye ait {postCount} makale bulunmaktadır. Önce makaleleri başka bir kategoriye taşıyın veya silin.";

    public const string CategoryHasPostsCannotDelete = "Makaleleri bulunan kategori silinemez";

    // State Messages
    public const string CategoryNotActive = "Category is not active";
    public const string CategoryAlreadyDeleted = "Category is already deleted";
}

