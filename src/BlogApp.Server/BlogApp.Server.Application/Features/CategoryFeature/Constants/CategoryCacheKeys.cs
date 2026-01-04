namespace BlogApp.Server.Application.Features.CategoryFeature.Constants;

/// <summary>
/// Cache key constants for category-related caching.
/// </summary>
public static class CategoryCacheKeys
{
    /// <summary>
    /// Cache versioning group name for category lists.
    /// Used with GetGroupVersionAsync/RotateGroupVersionAsync for efficient cache invalidation.
    /// </summary>
    public const string ListGroup = "categories_list";

    /// <summary>
    /// Prefix for category list caches: "categories:list"
    /// </summary>
    public const string ListPrefix = "categories:list";

    /// <summary>
    /// Prefix for individual category caches by id: "category:id:{id}"
    /// </summary>
    public const string IdPrefix = "category:id";

    /// <summary>
    /// Gets the cache key for a category by id.
    /// </summary>
    public static string ById(Guid id) => $"{IdPrefix}:{id}";

    /// <summary>
    /// Gets versioned cache key for category lists.
    /// </summary>
    public static string VersionedListKey(int version, string keySuffix) => $"v{version}:{ListPrefix}:{keySuffix}";
}

