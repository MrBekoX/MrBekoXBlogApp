namespace BlogApp.BuildingBlocks.Caching.Abstractions;

/// <summary>
/// Result of a cache get operation with staleness information for SWR pattern.
/// </summary>
/// <typeparam name="T">The type of cached value</typeparam>
/// <param name="Value">The cached value (may be null on cache miss)</param>
/// <param name="IsStale">Whether the value is stale and should trigger background refresh</param>
/// <param name="IsHit">Whether the value was found in cache</param>
public record CacheResult<T>(T? Value, bool IsStale, bool IsHit);
