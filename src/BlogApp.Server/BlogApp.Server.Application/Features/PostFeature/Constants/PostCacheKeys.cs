namespace BlogApp.Server.Application.Features.PostFeature.Constants;

/// <summary>
/// Cache key constants for post-related caching.
/// </summary>
public static class PostCacheKeys
{
    /// <summary>
    /// Cache versioning group name for post lists.
    /// Used with GetGroupVersionAsync/RotateGroupVersionAsync for efficient cache invalidation.
    /// </summary>
    public const string ListGroup = "posts_list";

    /// <summary>
    /// Prefix for post list caches: "posts:list"
    /// </summary>
    public const string ListPrefix = "posts:list";

    /// <summary>
    /// Prefix for individual post caches by slug: "post:slug:{slug}"
    /// </summary>
    public const string SlugPrefix = "post:slug";

    /// <summary>
    /// Prefix for individual post caches by id: "post:id:{id}"
    /// </summary>
    public const string IdPrefix = "post:id";

    /// <summary>
    /// Gets the cache key for a post by slug.
    /// </summary>
    public static string BySlug(string slug) => $"{SlugPrefix}:{slug}";

    /// <summary>
    /// Gets the cache key for a post by id.
    /// </summary>
    public static string ById(Guid id) => $"{IdPrefix}:{id}";

    /// <summary>
    /// Gets versioned cache key for post lists.
    /// </summary>
    public static string VersionedListKey(int version, string keySuffix) => $"v{version}:{ListPrefix}:{keySuffix}";
}

