using BlogApp.Server.Application.Common.Interfaces.Persistence;
using BlogApp.Server.Application.Common.Interfaces.Services;
using MediatR;
using Microsoft.Extensions.Logging;

namespace BlogApp.Server.Application.Common.Behaviors;

/// <summary>
/// Cache'lenebilir request'ler için interface.
/// Supports both standard caching and Stale-While-Revalidate (SWR) pattern.
/// </summary>
public interface ICacheableQuery
{
    /// <summary>
    /// Base cache key generated from request parameters.
    /// Return empty string to skip caching for this request.
    /// </summary>
    string CacheKey { get; }

    /// <summary>
    /// Cache group for version-based invalidation (e.g., "posts_list").
    /// </summary>
    string? CacheGroup { get; }

    /// <summary>
    /// Cache duration (hard expiration for standard, soft expiration for SWR).
    /// </summary>
    TimeSpan? CacheDuration { get; }

    /// <summary>
    /// If true, uses Stale-While-Revalidate pattern.
    /// Stale data is returned immediately while fresh data is fetched in background.
    /// </summary>
    bool UseStaleWhileRevalidate => false;

    /// <summary>
    /// For SWR: ratio of soft expiration to hard expiration.
    /// Default is 0.5 (soft = half of hard). Range: 0.1 to 0.9.
    /// Example: CacheDuration=10min, SwrSoftRatio=0.5 → soft=5min, hard=10min
    /// </summary>
    double SwrSoftRatio => 0.5;
}


/// <summary>
/// MediatR Pipeline için caching behavior.
/// Includes cache stampede protection via GetOrSetAsync.
/// Supports Stale-While-Revalidate (SWR) pattern for improved response times.
/// </summary>
public class CachingBehavior<TRequest, TResponse> : IPipelineBehavior<TRequest, TResponse>
    where TRequest : class, ICacheableQuery
{
    private readonly ICacheService _cacheService;
    private readonly ILogger<CachingBehavior<TRequest, TResponse>> _logger;

    public CachingBehavior(ICacheService cacheService, ILogger<CachingBehavior<TRequest, TResponse>> logger)
    {
        _cacheService = cacheService;
        _logger = logger;
    }

    public async Task<TResponse> Handle(TRequest request, RequestHandlerDelegate<TResponse> next, CancellationToken cancellationToken)
    {
        var cacheKey = request.CacheKey;

        // Skip caching if key is empty (e.g., requests with side effects like view count increment)
        if (string.IsNullOrWhiteSpace(cacheKey))
        {
            _logger.LogDebug("Skipping cache for request {RequestType} (empty cache key)", typeof(TRequest).Name);
            return await next();
        }

        // Build versioned cache key if using group versioning
        if (!string.IsNullOrWhiteSpace(request.CacheGroup))
        {
            var version = await _cacheService.GetGroupVersionAsync(request.CacheGroup!, cancellationToken);
            cacheKey = $"{request.CacheGroup}:v{version}:{cacheKey}";
        }

        var duration = request.CacheDuration ?? TimeSpan.FromMinutes(5);

        // Use SWR pattern if enabled
        if (request.UseStaleWhileRevalidate)
        {
            // Calculate soft and hard expiration based on ratio
            var ratio = Math.Clamp(request.SwrSoftRatio, 0.1, 0.9);
            var softExpiration = TimeSpan.FromTicks((long)(duration.Ticks * ratio));
            var hardExpiration = duration;

            _logger.LogDebug("Using SWR for {CacheKey} (soft: {Soft}s, hard: {Hard}s)",
                cacheKey, softExpiration.TotalSeconds, hardExpiration.TotalSeconds);

            // Use the scoped version that creates a new DI scope for background refresh
            return await _cacheService.GetOrSetWithSwrAsync<TRequest, TResponse>(
                cacheKey,
                request,
                async () =>
                {
                    _logger.LogDebug("SWR cache miss/refresh for {CacheKey}, executing handler", cacheKey);
                    return await next();
                },
                softExpiration,
                hardExpiration,
                cancellationToken
            );
        }

        // Standard caching with stampede protection
        var response = await _cacheService.GetOrSetAsync(
            cacheKey,
            async () =>
            {
                _logger.LogDebug("Cache miss for {CacheKey}, executing handler", cacheKey);
                return await next();
            },
            duration,
            cancellationToken
        );

        return response;
    }
}



