namespace BlogApp.Server.Application.Common.Interfaces;

/// <summary>
/// Result of a cache get operation with staleness information for SWR pattern.
/// </summary>
public record CacheResult<T>(T? Value, bool IsStale, bool IsHit);

/// <summary>
/// Cache servisi arayüzü.
/// Supports L1/L2 hybrid caching and Stale-While-Revalidate (SWR) pattern.
/// </summary>
public interface ICacheService
{
    Task<T?> GetAsync<T>(string key, CancellationToken cancellationToken = default);
    Task SetAsync<T>(string key, T value, TimeSpan? expiration = null, CancellationToken cancellationToken = default);
    Task RemoveAsync(string key, CancellationToken cancellationToken = default);
    Task RemoveByPrefixAsync(string prefix, CancellationToken cancellationToken = default);
    Task<bool> ExistsAsync(string key, CancellationToken cancellationToken = default);
    Task<T> GetOrSetAsync<T>(string key, Func<Task<T>> factory, TimeSpan? expiration = null, CancellationToken cancellationToken = default);

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
    /// <param name="softExpiration">Time after which value becomes stale (triggers background refresh)</param>
    /// <param name="hardExpiration">Time after which value is completely removed</param>
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
    /// <param name="softExpiration">Time after which value becomes stale</param>
    /// <param name="hardExpiration">Time after which value is removed (defaults to 2x soft)</param>
    Task<T> GetOrSetWithSwrAsync<T>(
        string key,
        Func<Task<T>> factory,
        TimeSpan softExpiration,
        TimeSpan? hardExpiration = null,
        CancellationToken cancellationToken = default);

    /// <summary>
    /// Gets or sets a value using Stale-While-Revalidate pattern with proper DI scope handling.
    /// Background refresh creates a new DI scope to avoid disposed context issues.
    /// - If fresh: returns cached value
    /// - If stale: returns cached value AND triggers background refresh in new scope
    /// - If miss: executes factory, caches result, returns value
    /// </summary>
    /// <typeparam name="TRequest">The MediatR request type</typeparam>
    /// <typeparam name="TResponse">The response type</typeparam>
    /// <param name="request">The request object to re-execute in background refresh</param>
    Task<TResponse> GetOrSetWithSwrAsync<TRequest, TResponse>(
        string key,
        TRequest request,
        Func<Task<TResponse>> factory,
        TimeSpan softExpiration,
        TimeSpan? hardExpiration = null,
        CancellationToken cancellationToken = default) where TRequest : class;

    #endregion
}
