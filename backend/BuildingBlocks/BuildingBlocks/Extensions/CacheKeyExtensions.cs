namespace BlogApp.BuildingBlocks.Extensions;

/// <summary>
/// Extension methods for cache key manipulation and extraction.
/// </summary>
public static class CacheKeyExtensions
{
    /// <summary>
    /// Extracts the prefix from a cache key for metric tagging.
    /// Sample: "post:slug:xyz" -> "post"
    /// </summary>
    public static string GetKeyPrefix(this string key)
    {
        if (string.IsNullOrEmpty(key))
            return "unknown";

        var colonIndex = key.IndexOf(':');
        return colonIndex > 0 ? key[..colonIndex] : key;
    }

    /// <summary>
    /// Creates a versioned cache key using the group version strategy.
    /// Sample: "posts", 5, "slug:xyz" -> "posts:v5:slug:xyz"
    /// </summary>
    public static string ToVersionedKey(this string baseKey, string group, long version)
    {
        return $"{group}:v{version}:{baseKey}";
    }

    /// <summary>
    /// Creates a cache key with multiple segments.
    /// Sample: ["posts", "published", "page", "1"] -> "posts:published:page:1"
    /// </summary>
    public static string ToCacheKey(this IEnumerable<string> segments)
    {
        return string.Join(":", segments.Where(s => !string.IsNullOrEmpty(s)));
    }

    /// <summary>
    /// Creates a cache key with multiple segments.
    /// Sample: ToCacheKey("posts", "published", "page", 1) -> "posts:published:page:1"
    /// </summary>
    public static string ToCacheKey(params object[] segments)
    {
        return string.Join(":", segments.Where(s => s != null).Select(s => s.ToString()));
    }
}
