namespace BlogApp.BuildingBlocks.Caching.Abstractions;

/// <summary>
/// Hybrid L1/L2 cache service interface with advanced features:
/// - L1: In-memory cache (ultra fast, no network, short TTL)
/// - L2: Distributed cache (Redis - shared across instances, longer TTL)
/// - Stale-While-Revalidate (SWR) pattern
/// - Cache group versioning
/// - Prefix-based invalidation
///
/// For basic caching needs, use IBasicCacheService instead.
/// </summary>
public interface IHybridCacheService : IBasicCacheService
{
    /// <summary>
    /// Remove all cache entries with keys starting with the specified prefix.
    /// Uses Redis SCAN for efficient prefix-based deletion.
    /// </summary>
    Task RemoveByPrefixAsync(string prefix, CancellationToken cancellationToken = default);

    /// <summary>
    /// Gets the current version number for a cache group.
    /// Used for cache versioning strategy to invalidate groups of cached items.
    /// </summary>
    Task<long> GetGroupVersionAsync(string groupName, CancellationToken cancellationToken = default);

    /// <summary>
    /// Increments the version number for a cache group.
    /// All cache keys using the old version become orphaned and will eventually expire.
    /// </summary>
    Task RotateGroupVersionAsync(string groupName, CancellationToken cancellationToken = default);

    #region Stale-While-Revalidate (SWR) Support

    /// <summary>
    /// Sets a value with separate soft (stale) and hard expiration times.
    /// After soft expiration: value is stale but still returned, triggers background refresh.
    /// After hard expiration: value is completely removed.
    /// </summary>
    /// <param name="key">Cache key</param>
    /// <param name="value">Value to cache</param>
    /// <param name="softExpiration">Time after which value becomes stale (triggers background refresh)</param>
    /// <param name="hardExpiration">Time after which value is completely removed</param>
    /// <param name="cancellationToken">Cancellation token</param>
    Task SetWithSoftExpirationAsync<T>(
        string key,
        T value,
        TimeSpan softExpiration,
        TimeSpan hardExpiration,
        CancellationToken cancellationToken = default);

    /// <summary>
    /// Gets a value with staleness information for SWR pattern.
    /// Returns (value, isStale) where isStale indicates if background refresh should be triggered.
    /// </summary>
    Task<CacheResult<T>> GetWithMetadataAsync<T>(string key, CancellationToken cancellationToken = default);

    /// <summary>
    /// Gets or sets a value using Stale-While-Revalidate pattern.
    /// - If fresh: returns cached value
    /// - If stale: returns cached value AND triggers background refresh
    /// - If miss: executes factory, caches result, returns value
    /// </summary>
    /// <param name="key">Cache key</param>
    /// <param name="factory">Factory function to create value on cache miss</param>
    /// <param name="softExpiration">Time after which value becomes stale</param>
    /// <param name="hardExpiration">Time after which value is removed (defaults to 2x soft)</param>
    /// <param name="cancellationToken">Cancellation token</param>
    Task<T> GetOrSetWithSwrAsync<T>(
        string key,
        Func<Task<T>> factory,
        TimeSpan softExpiration,
        TimeSpan? hardExpiration = null,
        CancellationToken cancellationToken = default);

    #endregion
}
