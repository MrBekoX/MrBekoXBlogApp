using BlogApp.BuildingBlocks.Caching.Abstractions;
using BlogApp.BuildingBlocks.Caching.Extensions;
using BlogApp.BuildingBlocks.Caching.Metrics;
using BlogApp.BuildingBlocks.Caching.Options;
using BlogApp.BuildingBlocks.Caching.Services;
using BlogApp.Server.Application.Common.Interfaces.Services;
using MediatR;
using Microsoft.Extensions.Caching.Distributed;
using Microsoft.Extensions.Caching.Memory;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;
using StackExchange.Redis;
using System.Collections.Concurrent;

namespace BlogApp.Server.Infrastructure.Services;

/// <summary>
/// Domain-specific cache service implementation for BlogApp.
/// Extends HybridCacheServiceBase with:
/// - Frontend cache invalidation notifications via ICacheInvalidationNotifier
/// - MediatR-scoped SWR for proper DI handling in background refreshes
/// - Deduplication of concurrent refresh tasks to prevent task accumulation
/// </summary>
public class CacheService : HybridCacheServiceBase, ICacheService
{
    private readonly ICacheInvalidationNotifier? _notifier;
    private readonly IServiceScopeFactory? _serviceScopeFactory;
    // BUG-004: Track ongoing refresh tasks to prevent accumulation
    private readonly ConcurrentDictionary<string, Task> _ongoingRefreshes = new();

    public CacheService(
        IMemoryCache l1Cache,
        IDistributedCache l2Cache,
        ILogger<CacheService> logger,
        CacheMetrics metrics,
        IOptions<RedisSettings> redisSettings,
        ICacheInvalidationNotifier? notifier = null,
        IConnectionMultiplexer? redis = null,
        IServiceScopeFactory? serviceScopeFactory = null)
        : base(l1Cache, l2Cache, logger, metrics, redisSettings, redis)
    {
        _notifier = notifier;
        _serviceScopeFactory = serviceScopeFactory;
    }

    #region Domain-Specific Hooks (Frontend Notifications)

    protected override async Task OnKeyRemovedAsync(string key, CancellationToken cancellationToken)
    {
        if (_notifier != null)
        {
            _ = _notifier.NotifyKeyRemovedAsync(key, CancellationToken.None);
        }

        await base.OnKeyRemovedAsync(key, cancellationToken);
    }

    protected override async Task OnPrefixRemovedAsync(string prefix, CancellationToken cancellationToken)
    {
        if (_notifier != null)
        {
            _ = _notifier.NotifyPrefixRemovedAsync(prefix, CancellationToken.None);
        }

        await base.OnPrefixRemovedAsync(prefix, cancellationToken);
    }

    protected override async Task OnGroupInvalidatedAsync(string groupName, CancellationToken cancellationToken)
    {
        if (_notifier != null)
        {
            _ = _notifier.NotifyGroupInvalidatedAsync(groupName, CancellationToken.None);
        }

        await base.OnGroupInvalidatedAsync(groupName, cancellationToken);
    }

    #endregion

    #region MediatR-Scoped SWR Implementation

    /// <summary>
    /// SWR with proper DI scope handling for background refresh.
    /// Creates a new scope and uses IMediator to re-execute the request.
    /// </summary>
    public async Task<TResponse> GetOrSetWithSwrAsync<TRequest, TResponse>(
        string key,
        TRequest request,
        Func<Task<TResponse>> factory,
        TimeSpan softExpiration,
        TimeSpan? hardExpiration = null,
        CancellationToken cancellationToken = default) where TRequest : class
    {
        using var scope = Metrics.StartOperation("get_or_set_swr_scoped", key);
        var keyPrefix = key.GetKeyPrefix();

        // Default hard expiration is 2x soft expiration
        var actualHardExpiration = hardExpiration ?? TimeSpan.FromTicks(softExpiration.Ticks * 2);

        // Check cache with metadata
        var result = await GetWithMetadataAsync<TResponse>(key, cancellationToken);

        if (result.IsHit)
        {
            if (result.IsStale)
            {
                // Return stale value immediately, but trigger background refresh with NEW SCOPE
                Logger.LogDebug("SWR (scoped): Returning stale value for {Key}, triggering background refresh", key);
                Metrics.RecordSwrBackgroundRefresh(keyPrefix);

                // BUG-004: Check if refresh is already in progress for this key
                var refreshKey = $"swr_refresh:{key}";
                var existingTask = _ongoingRefreshes.TryGetValue(refreshKey, out var ongoingTask);

                if (existingTask && ongoingTask is not null && !ongoingTask.IsCompleted)
                {
                    Logger.LogDebug("SWR: Background refresh already in progress for {Key}, skipping duplicate", key);
                    return result.Value!;
                }

                // Background refresh with proper DI scope and deduplication
                var backgroundTask = Task.Run(async () =>
                {
                    try
                    {
                        if (_serviceScopeFactory == null)
                        {
                            Logger.LogWarning("SWR: IServiceScopeFactory not available, cannot perform background refresh for {Key}", key);
                            return;
                        }

                        // Create a new DI scope for background work
                        using var backgroundScope = _serviceScopeFactory.CreateScope();
                        var mediator = backgroundScope.ServiceProvider.GetRequiredService<IMediator>();

                        // Re-execute the request with fresh services
                        var freshValue = await mediator.Send(request, CancellationToken.None);

                        await SetWithSoftExpirationAsync(key, freshValue, softExpiration, actualHardExpiration, CancellationToken.None);
                        Logger.LogDebug("SWR: Background refresh completed for {Key}", key);
                    }
                    catch (Exception ex)
                    {
                        Logger.LogWarning(ex, "SWR: Background refresh failed for {Key}", key);
                        Metrics.RecordSwrBackgroundRefreshError(keyPrefix);
                    }
                    finally
                    {
                        // BUG-004: Remove from tracking when complete
                        _ongoingRefreshes.TryRemove(refreshKey, out _);
                    }
                }, CancellationToken.None);

                // BUG-004: Track this refresh task
                _ongoingRefreshes.TryAdd(refreshKey, backgroundTask);

                // Configure continuation to handle unobserved exceptions
                _ = backgroundTask.ContinueWith(t =>
                {
                    if (t.IsFaulted)
                    {
                        Logger.LogError(t.Exception, "SWR: Unobserved exception in background refresh for {Key}", key);
                    }
                }, TaskContinuationOptions.OnlyOnFaulted);

                return result.Value!;
            }

            // Fresh hit - return immediately
            return result.Value!;
        }

        // Cache miss - need to execute factory with stampede protection
        return await ExecuteWithStampedeProtectionAsync(key, factory, softExpiration, actualHardExpiration, keyPrefix, cancellationToken);
    }

    private async Task<T> ExecuteWithStampedeProtectionAsync<T>(
        string key,
        Func<Task<T>> factory,
        TimeSpan softExpiration,
        TimeSpan hardExpiration,
        string keyPrefix,
        CancellationToken cancellationToken)
    {
        // Use the base class GetOrSetWithSwrAsync for stampede protection
        // This is a workaround since we can't access _locks from base
        return await base.GetOrSetWithSwrAsync(key, factory, softExpiration, hardExpiration, cancellationToken);
    }

    #endregion
}
