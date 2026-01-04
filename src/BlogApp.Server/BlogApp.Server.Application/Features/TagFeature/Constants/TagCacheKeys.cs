namespace BlogApp.Server.Application.Features.TagFeature.Constants;

/// <summary>
/// Cache key constants for tag-related caching.
/// </summary>
public static class TagCacheKeys
{
    /// <summary>
    /// Cache versioning group name for tag lists.
    /// Used with GetGroupVersionAsync/RotateGroupVersionAsync for efficient cache invalidation.
    /// </summary>
    public const string ListGroup = "tags_list";

    /// <summary>
    /// Prefix for tag list caches: "tags:list"
    /// </summary>
    public const string ListPrefix = "tags:list";

    /// <summary>
    /// Prefix for individual tag caches by id: "tag:id:{id}"
    /// </summary>
    public const string IdPrefix = "tag:id";

    /// <summary>
    /// Gets the cache key for a tag by id.
    /// </summary>
    public static string ById(Guid id) => $"{IdPrefix}:{id}";

    /// <summary>
    /// Gets versioned cache key for tag lists.
    /// </summary>
    public static string VersionedListKey(int version, string keySuffix) => $"v{version}:{ListPrefix}:{keySuffix}";
}

