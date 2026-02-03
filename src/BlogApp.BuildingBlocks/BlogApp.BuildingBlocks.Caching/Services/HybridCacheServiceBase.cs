using System.Collections.Concurrent;
using System.Text.Json;
using BlogApp.BuildingBlocks.Caching.Abstractions;
using BlogApp.BuildingBlocks.Caching.Extensions;
using BlogApp.BuildingBlocks.Caching.Metrics;
using BlogApp.BuildingBlocks.Caching.Options;
using Microsoft.Extensions.Caching.Distributed;
using Microsoft.Extensions.Caching.Memory;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;
using StackExchange.Redis;

namespace BlogApp.BuildingBlocks.Caching.Services;

/// <summary>
/// Abstract base class for hybrid L1/L2 cache service implementation.
///
/// Features:
/// - L1: In-memory cache (IMemoryCache) - ultra fast, no network, short TTL
/// - L2: Distributed cache (Redis/IDistributedCache) - shared across instances, longer TTL
/// - Cache stampede protection using key-based locking
/// - SCAN-based prefix invalidation for Redis
/// - Automatic L2 to L1 promotion on cache hits
/// - Write-through: writes go to both L1 and L2
/// - Stale-While-Revalidate (SWR) pattern support
/// - Metrics for observability
///
/// Derived classes can override hooks for domain-specific behavior:
/// - OnKeyRemoved: Called when a key is removed
/// - OnPrefixRemoved: Called when keys with prefix are removed
/// - OnGroupInvalidated: Called when a cache group is invalidated
/// - OnSwrBackgroundRefreshNeeded: Called when SWR background refresh is triggered
/// </summary>
public abstract class HybridCacheServiceBase : IHybridCacheService, IDisposable
{
    protected readonly IMemoryCache L1Cache;
    protected readonly IDistributedCache L2Cache;
    protected readonly IConnectionMultiplexer? Redis;
    protected readonly ILogger Logger;
    protected readonly CacheMetrics Metrics;
    protected readonly string InstancePrefix;

    private readonly Timer _cleanupTimer;
    private readonly ConcurrentDictionary<string, DateTimeOffset> _keyExpirations = new();
    private readonly ConcurrentDictionary<string, SemaphoreSlim> _locks = new();
    private int _l1KeyCount;
    private bool _disposed;

    // L1 cache settings (short TTL for consistency across instances)
    protected static readonly TimeSpan L1DefaultExpiration = TimeSpan.FromSeconds(30);
    protected static readonly TimeSpan L1MaxExpiration = TimeSpan.FromMinutes(2);

    // L2 cache settings
    protected static readonly TimeSpan L2DefaultExpiration = TimeSpan.FromMinutes(5);

    // General settings
    protected static readonly TimeSpan CleanupInterval = TimeSpan.FromMinutes(5);
    protected static readonly TimeSpan LockTimeout = TimeSpan.FromSeconds(30);
    protected const int MaxTrackedKeys = 10000;
    protected const int MaxTrackedLocks = 1000;

    protected HybridCacheServiceBase(
        IMemoryCache l1Cache,
        IDistributedCache l2Cache,
        ILogger logger,
        CacheMetrics metrics,
        IOptions<RedisSettings> redisSettings,
        IConnectionMultiplexer? redis = null)
    {
        L1Cache = l1Cache;
        L2Cache = l2Cache;
        Logger = logger;
        Metrics = metrics;
        Redis = redis;
        InstancePrefix = redisSettings.Value.InstanceName;

        // Start periodic cleanup timer
        _cleanupTimer = new Timer(CleanupExpiredKeys, null, CleanupInterval, CleanupInterval);
    }

    #region IBasicCacheService Implementation

    public async Task<T?> GetAsync<T>(string key, CancellationToken cancellationToken = default)
    {
        using var scope = Metrics.StartOperation("get", key);
        var keyPrefix = key.GetKeyPrefix();

        try
        {
            // L1 check first (no network, ultra fast)
            if (L1Cache.TryGetValue(key, out T? l1Value))
            {
                Metrics.RecordL1Hit(keyPrefix);
                Logger.LogDebug("L1 cache hit for key {Key}", key);
                return l1Value;
            }

            Metrics.RecordL1Miss(keyPrefix);

            // L2 check (Redis/distributed cache)
            var l2Data = await L2Cache.GetStringAsync(key, cancellationToken);

            if (string.IsNullOrEmpty(l2Data))
            {
                Metrics.RecordL2Miss(keyPrefix);
                _keyExpirations.TryRemove(key, out _);
                return default;
            }

            Metrics.RecordL2Hit(keyPrefix);

            // Deserialize and promote to L1
            var value = JsonSerializer.Deserialize<T>(l2Data);
            if (value is not null)
            {
                PromoteToL1(key, value);
                Metrics.RecordL1Promotion(keyPrefix);
            }

            return value;
        }
        catch (Exception ex)
        {
            Logger.LogWarning(ex, "Error getting cache key {Key}", key);
            Metrics.RecordError("get", keyPrefix);
            return default;
        }
    }

    public async Task SetAsync<T>(string key, T value, TimeSpan? expiration = null, CancellationToken cancellationToken = default)
    {
        using var scope = Metrics.StartOperation("set", key);
        var keyPrefix = key.GetKeyPrefix();

        try
        {
            var l2Expiration = expiration ?? L2DefaultExpiration;

            // Write-through: write to both L1 and L2
            // L1 with shorter TTL
            var l1Expiration = CalculateL1Expiration(l2Expiration);
            SetL1(key, value, l1Expiration);

            // L2 with full TTL
            var options = new DistributedCacheEntryOptions
            {
                AbsoluteExpirationRelativeToNow = l2Expiration
            };

            var data = JsonSerializer.Serialize(value);
            await L2Cache.SetStringAsync(key, data, options, cancellationToken);

            // Track key with expiration time for cleanup
            TrackKey(key, l2Expiration);
            Metrics.RecordWrite(keyPrefix);

            Logger.LogDebug("Cache set for key {Key} (L1: {L1TTL}s, L2: {L2TTL}s)",
                key, l1Expiration.TotalSeconds, l2Expiration.TotalSeconds);
        }
        catch (Exception ex)
        {
            Logger.LogWarning(ex, "Error setting cache key {Key}", key);
            Metrics.RecordError("set", keyPrefix);
        }
    }

    public async Task RemoveAsync(string key, CancellationToken cancellationToken = default)
    {
        using var scope = Metrics.StartOperation("remove", key);
        var keyPrefix = key.GetKeyPrefix();

        try
        {
            // Remove from both layers
            L1Cache.Remove(key);
            Interlocked.Decrement(ref _l1KeyCount);

            await L2Cache.RemoveAsync(key, cancellationToken);
            _keyExpirations.TryRemove(key, out _);

            Metrics.RecordRemoval(keyPrefix);
            Logger.LogDebug("Cache removed for key {Key}", key);

            // Hook for derived classes
            await OnKeyRemovedAsync(key, cancellationToken);
        }
        catch (Exception ex)
        {
            Logger.LogWarning(ex, "Error removing cache key {Key}", key);
            Metrics.RecordError("remove", keyPrefix);
        }
    }

    public async Task<bool> ExistsAsync(string key, CancellationToken cancellationToken = default)
    {
        try
        {
            // Check L1 first
            if (L1Cache.TryGetValue(key, out _))
                return true;

            // Check L2
            var data = await L2Cache.GetStringAsync(key, cancellationToken);
            var exists = !string.IsNullOrEmpty(data);

            if (!exists)
            {
                _keyExpirations.TryRemove(key, out _);
            }

            return exists;
        }
        catch (Exception ex)
        {
            Logger.LogWarning(ex, "Error checking cache key {Key}", key);
            return false;
        }
    }

    public async Task<T> GetOrSetAsync<T>(string key, Func<Task<T>> factory, TimeSpan? expiration = null, CancellationToken cancellationToken = default)
    {
        using var scope = Metrics.StartOperation("get_or_set", key);
        var keyPrefix = key.GetKeyPrefix();

        // First check - L1 (no lock needed, ultra fast)
        if (L1Cache.TryGetValue(key, out T? l1Value))
        {
            Metrics.RecordL1Hit(keyPrefix);
            return l1Value!;
        }

        Metrics.RecordL1Miss(keyPrefix);

        // Check L2 before acquiring lock
        var cached = await GetFromL2Async<T>(key, keyPrefix, cancellationToken);
        if (cached is not null)
            return cached;

        // Get or create a lock for this specific key
        var keyLock = _locks.GetOrAdd(key, _ => new SemaphoreSlim(1, 1));

        var lockAcquired = false;
        try
        {
            // Try to acquire lock with timeout to prevent deadlocks
            lockAcquired = await keyLock.WaitAsync(LockTimeout, cancellationToken);

            if (!lockAcquired)
            {
                Logger.LogWarning("Lock timeout for cache key {Key}, executing factory without lock", key);
                Metrics.RecordLockTimeout(keyPrefix);

                // Fallback: execute factory without lock (better than hanging)
                var fallbackValue = await factory();
                await SetAsync(key, fallbackValue, expiration, cancellationToken);
                return fallbackValue;
            }

            // Double-check L1 after acquiring lock
            if (L1Cache.TryGetValue(key, out l1Value))
            {
                Logger.LogDebug("L1 cache hit after lock for key {Key} (stampede prevented)", key);
                Metrics.RecordStampedePrevented(keyPrefix);
                Metrics.RecordL1Hit(keyPrefix);
                return l1Value!;
            }

            // Double-check L2 after acquiring lock
            cached = await GetFromL2Async<T>(key, keyPrefix, cancellationToken);
            if (cached is not null)
            {
                Logger.LogDebug("L2 cache hit after lock for key {Key} (stampede prevented)", key);
                Metrics.RecordStampedePrevented(keyPrefix);
                return cached;
            }

            // We're the first one - execute factory and cache the result
            Logger.LogDebug("Executing factory for cache key {Key}", key);
            var value = await factory();
            await SetAsync(key, value, expiration, cancellationToken);

            return value;
        }
        finally
        {
            if (lockAcquired)
            {
                keyLock.Release();
            }

            CleanupLockIfUnused(key, keyLock);
        }
    }

    #endregion

    #region IHybridCacheService Implementation

    public async Task RemoveByPrefixAsync(string prefix, CancellationToken cancellationToken = default)
    {
        try
        {
            var removedCount = 0;

            // Remove from L1 (in-memory tracking based)
            var l1KeysToRemove = _keyExpirations.Keys
                .Where(k => k.StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
                .ToList();

            foreach (var key in l1KeysToRemove)
            {
                L1Cache.Remove(key);
                Interlocked.Decrement(ref _l1KeyCount);
            }

            // Remove from L2
            if (Redis != null && Redis.IsConnected)
            {
                removedCount = await RemoveByPrefixRedisAsync(prefix, cancellationToken);
            }
            else
            {
                removedCount = await RemoveByPrefixInMemoryAsync(prefix, cancellationToken);
            }

            Logger.LogDebug("Removed {Count} cache keys with prefix: {Prefix}", removedCount, prefix);

            // Hook for derived classes
            if (removedCount > 0)
            {
                await OnPrefixRemovedAsync(prefix, cancellationToken);
            }
        }
        catch (Exception ex)
        {
            Logger.LogWarning(ex, "Error removing cache keys with prefix {Prefix}", prefix);
        }
    }

    public async Task<long> GetGroupVersionAsync(string groupName, CancellationToken cancellationToken = default)
    {
        var versionKey = $"cache_version:{groupName}";

        try
        {
            // Redis path (preferred for atomic operations)
            if (Redis?.IsConnected == true)
            {
                var db = Redis.GetDatabase();
                var value = await db.StringGetAsync(versionKey);

                if (value.HasValue && long.TryParse(value.ToString(), out var v))
                    return v;

                return 1;
            }

            // Fallback: distributed cache
            var data = await L2Cache.GetStringAsync(versionKey, cancellationToken);

            if (!string.IsNullOrWhiteSpace(data) && long.TryParse(data, out var v2))
                return v2;

            return 1;
        }
        catch (Exception ex)
        {
            Logger.LogWarning(ex, "Error getting cache group version for {GroupName}, returning default", groupName);
            return 1;
        }
    }

    public async Task RotateGroupVersionAsync(string groupName, CancellationToken cancellationToken = default)
    {
        var versionKey = $"cache_version:{groupName}";

        try
        {
            // Redis path: atomic INCR
            if (Redis != null && Redis.IsConnected)
            {
                var db = Redis.GetDatabase();
                var newVersion = await db.StringIncrementAsync(versionKey);
                Logger.LogDebug("Rotated cache version for group {GroupName} to {Version}", groupName, newVersion);

                // Clear L1 cache for this group (approximate - clear all tracked keys with group prefix)
                ClearL1ByPrefix($"{groupName}:");

                // Hook for derived classes
                await OnGroupInvalidatedAsync(groupName, cancellationToken);
                return;
            }

            // Fallback: get + set (not atomic but works for single instance)
            var currentVersion = await GetGroupVersionAsync(groupName, cancellationToken);
            var newVersionFallback = currentVersion + 1;

            var options = new DistributedCacheEntryOptions
            {
                AbsoluteExpirationRelativeToNow = TimeSpan.FromDays(365)
            };

            await L2Cache.SetStringAsync(versionKey, newVersionFallback.ToString(), options, cancellationToken);
            Logger.LogDebug("Rotated cache version for group {GroupName} to {Version} (fallback mode)", groupName, newVersionFallback);

            ClearL1ByPrefix($"{groupName}:");

            // Hook for derived classes
            await OnGroupInvalidatedAsync(groupName, cancellationToken);
        }
        catch (Exception ex)
        {
            Logger.LogWarning(ex, "Error rotating cache group version for {GroupName}", groupName);
        }
    }

    #endregion

    #region Stale-While-Revalidate (SWR) Implementation

    /// <summary>
    /// Wrapper class for cache entries with SWR metadata.
    /// </summary>
    protected sealed record SwrCacheEntry<T>(T Value, DateTimeOffset SoftExpiration);

    public async Task SetWithSoftExpirationAsync<T>(
        string key,
        T value,
        TimeSpan softExpiration,
        TimeSpan hardExpiration,
        CancellationToken cancellationToken = default)
    {
        using var scope = Metrics.StartOperation("set_swr", key);
        var keyPrefix = key.GetKeyPrefix();

        try
        {
            var softExpirationTime = DateTimeOffset.UtcNow.Add(softExpiration);
            var entry = new SwrCacheEntry<T>(value, softExpirationTime);

            // Write-through to L1 with shorter TTL
            var l1Expiration = CalculateL1Expiration(hardExpiration);
            SetL1(key, entry, l1Expiration);

            // Write to L2 with hard expiration
            var options = new DistributedCacheEntryOptions
            {
                AbsoluteExpirationRelativeToNow = hardExpiration
            };

            var data = JsonSerializer.Serialize(entry);
            await L2Cache.SetStringAsync(key, data, options, cancellationToken);

            TrackKey(key, hardExpiration);
            Metrics.RecordWrite(keyPrefix);

            Logger.LogDebug(
                "SWR cache set for key {Key} (soft: {SoftTTL}s, hard: {HardTTL}s)",
                key, softExpiration.TotalSeconds, hardExpiration.TotalSeconds);
        }
        catch (Exception ex)
        {
            Logger.LogWarning(ex, "Error setting SWR cache key {Key}", key);
            Metrics.RecordError("set_swr", keyPrefix);
        }
    }

    public async Task<CacheResult<T>> GetWithMetadataAsync<T>(string key, CancellationToken cancellationToken = default)
    {
        using var scope = Metrics.StartOperation("get_swr", key);
        var keyPrefix = key.GetKeyPrefix();

        try
        {
            // Check L1 first
            if (L1Cache.TryGetValue(key, out SwrCacheEntry<T>? l1Entry) && l1Entry is not null)
            {
                Metrics.RecordL1Hit(keyPrefix);
                var isStale = DateTimeOffset.UtcNow > l1Entry.SoftExpiration;

                if (isStale)
                    Metrics.RecordSwrStaleHit(keyPrefix);
                else
                    Metrics.RecordSwrFreshHit(keyPrefix);

                return new CacheResult<T>(l1Entry.Value, isStale, true);
            }

            Metrics.RecordL1Miss(keyPrefix);

            // Check L2
            var l2Data = await L2Cache.GetStringAsync(key, cancellationToken);

            if (string.IsNullOrEmpty(l2Data))
            {
                Metrics.RecordL2Miss(keyPrefix);
                return new CacheResult<T>(default, false, false);
            }

            Metrics.RecordL2Hit(keyPrefix);

            var entry = JsonSerializer.Deserialize<SwrCacheEntry<T>>(l2Data);
            if (entry is null)
            {
                return new CacheResult<T>(default, false, false);
            }

            // Promote to L1
            PromoteToL1(key, entry);
            Metrics.RecordL1Promotion(keyPrefix);

            var stale = DateTimeOffset.UtcNow > entry.SoftExpiration;

            if (stale)
                Metrics.RecordSwrStaleHit(keyPrefix);
            else
                Metrics.RecordSwrFreshHit(keyPrefix);

            return new CacheResult<T>(entry.Value, stale, true);
        }
        catch (Exception ex)
        {
            Logger.LogWarning(ex, "Error getting SWR cache key {Key}", key);
            Metrics.RecordError("get_swr", keyPrefix);
            return new CacheResult<T>(default, false, false);
        }
    }

    public async Task<T> GetOrSetWithSwrAsync<T>(
        string key,
        Func<Task<T>> factory,
        TimeSpan softExpiration,
        TimeSpan? hardExpiration = null,
        CancellationToken cancellationToken = default)
    {
        using var scope = Metrics.StartOperation("get_or_set_swr", key);
        var keyPrefix = key.GetKeyPrefix();

        // Default hard expiration is 2x soft expiration
        var actualHardExpiration = hardExpiration ?? TimeSpan.FromTicks(softExpiration.Ticks * 2);

        // Check cache with metadata
        var result = await GetWithMetadataAsync<T>(key, cancellationToken);

        if (result.IsHit)
        {
            if (result.IsStale)
            {
                // Return stale value immediately, but trigger background refresh
                Logger.LogDebug("SWR: Returning stale value for {Key}, triggering background refresh", key);
                Metrics.RecordSwrBackgroundRefresh(keyPrefix);

                // Hook for derived classes to handle background refresh
                _ = OnSwrBackgroundRefreshNeededAsync(key, factory, softExpiration, actualHardExpiration, keyPrefix);

                return result.Value!;
            }

            // Fresh hit - return immediately
            return result.Value!;
        }

        // Cache miss - need to execute factory with stampede protection
        var keyLock = _locks.GetOrAdd(key, _ => new SemaphoreSlim(1, 1));

        var lockAcquired = false;
        try
        {
            lockAcquired = await keyLock.WaitAsync(LockTimeout, cancellationToken);

            if (!lockAcquired)
            {
                Logger.LogWarning("SWR: Lock timeout for cache key {Key}, executing factory without lock", key);
                Metrics.RecordLockTimeout(keyPrefix);

                var fallbackValue = await factory();
                await SetWithSoftExpirationAsync(key, fallbackValue, softExpiration, actualHardExpiration, cancellationToken);
                return fallbackValue;
            }

            // Double-check after acquiring lock
            result = await GetWithMetadataAsync<T>(key, cancellationToken);

            if (result.IsHit)
            {
                Metrics.RecordStampedePrevented(keyPrefix);

                if (result.IsStale)
                {
                    // Another request got the lock but the value is still stale
                    // We have the lock, so we'll do the refresh synchronously
                    Logger.LogDebug("SWR: Stale hit after lock for {Key}, refreshing synchronously", key);
                    var freshValue = await factory();
                    await SetWithSoftExpirationAsync(key, freshValue, softExpiration, actualHardExpiration, cancellationToken);
                    return freshValue;
                }

                return result.Value!;
            }

            // Execute factory and cache result
            Logger.LogDebug("SWR: Cache miss for {Key}, executing factory", key);
            var value = await factory();
            await SetWithSoftExpirationAsync(key, value, softExpiration, actualHardExpiration, cancellationToken);

            return value;
        }
        finally
        {
            if (lockAcquired)
            {
                keyLock.Release();
            }

            CleanupLockIfUnused(key, keyLock);
        }
    }

    #endregion

    #region Protected Hooks for Derived Classes

    /// <summary>
    /// Called when a cache key is removed. Override to add domain-specific behavior.
    /// </summary>
    protected virtual Task OnKeyRemovedAsync(string key, CancellationToken cancellationToken)
    {
        return Task.CompletedTask;
    }

    /// <summary>
    /// Called when cache keys with a prefix are removed. Override to add domain-specific behavior.
    /// </summary>
    protected virtual Task OnPrefixRemovedAsync(string prefix, CancellationToken cancellationToken)
    {
        return Task.CompletedTask;
    }

    /// <summary>
    /// Called when a cache group is invalidated. Override to add domain-specific behavior.
    /// </summary>
    protected virtual Task OnGroupInvalidatedAsync(string groupName, CancellationToken cancellationToken)
    {
        return Task.CompletedTask;
    }

    /// <summary>
    /// Called when SWR background refresh is needed. Override to implement custom background refresh logic.
    /// Default implementation uses Task.Run with error handling.
    /// </summary>
    protected virtual async Task OnSwrBackgroundRefreshNeededAsync<T>(
        string key,
        Func<Task<T>> factory,
        TimeSpan softExpiration,
        TimeSpan hardExpiration,
        string keyPrefix)
    {
        var backgroundTask = Task.Run(async () =>
        {
            try
            {
                var freshValue = await factory();
                await SetWithSoftExpirationAsync(key, freshValue, softExpiration, hardExpiration, CancellationToken.None);
                Logger.LogDebug("SWR: Background refresh completed for {Key}", key);
            }
            catch (Exception ex)
            {
                Logger.LogWarning(ex, "SWR: Background refresh failed for {Key}", key);
                Metrics.RecordSwrBackgroundRefreshError(keyPrefix);
            }
        }, CancellationToken.None);

        // Configure continuation to handle unobserved exceptions
        _ = backgroundTask.ContinueWith(t =>
        {
            if (t.IsFaulted)
            {
                Logger.LogError(t.Exception, "SWR: Unobserved exception in background refresh for {Key}", key);
            }
        }, TaskContinuationOptions.OnlyOnFaulted);

        await Task.CompletedTask;
    }

    #endregion

    #region Protected Helper Methods

    protected async Task<T?> GetFromL2Async<T>(string key, string keyPrefix, CancellationToken cancellationToken)
    {
        var l2Data = await L2Cache.GetStringAsync(key, cancellationToken);

        if (string.IsNullOrEmpty(l2Data))
        {
            Metrics.RecordL2Miss(keyPrefix);
            return default;
        }

        Metrics.RecordL2Hit(keyPrefix);

        var value = JsonSerializer.Deserialize<T>(l2Data);
        if (value is not null)
        {
            PromoteToL1(key, value);
            Metrics.RecordL1Promotion(keyPrefix);
        }

        return value;
    }

    protected void SetL1<T>(string key, T value, TimeSpan expiration)
    {
        var options = new MemoryCacheEntryOptions
        {
            AbsoluteExpirationRelativeToNow = expiration
        };

        // Track eviction
        options.RegisterPostEvictionCallback((evictedKey, _, _, _) =>
        {
            Interlocked.Decrement(ref _l1KeyCount);
            Logger.LogDebug("L1 cache evicted key {Key}", evictedKey);
        });

        L1Cache.Set(key, value, options);
        Interlocked.Increment(ref _l1KeyCount);
    }

    protected void PromoteToL1<T>(string key, T value)
    {
        // Promote with default L1 TTL
        SetL1(key, value, L1DefaultExpiration);
    }

    protected static TimeSpan CalculateL1Expiration(TimeSpan l2Expiration)
    {
        // L1 TTL is 1/10th of L2 TTL, capped between 10 seconds and 2 minutes
        var l1Ttl = TimeSpan.FromTicks(l2Expiration.Ticks / 10);

        if (l1Ttl < TimeSpan.FromSeconds(10))
            return TimeSpan.FromSeconds(10);

        if (l1Ttl > L1MaxExpiration)
            return L1MaxExpiration;

        return l1Ttl;
    }

    protected void ClearL1ByPrefix(string prefix)
    {
        var keysToRemove = _keyExpirations.Keys
            .Where(k => k.StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
            .ToList();

        foreach (var key in keysToRemove)
        {
            L1Cache.Remove(key);
            Interlocked.Decrement(ref _l1KeyCount);
        }

        if (keysToRemove.Count > 0)
        {
            Logger.LogDebug("Cleared {Count} L1 cache entries with prefix {Prefix}", keysToRemove.Count, prefix);
        }
    }

    #endregion

    #region Private Helper Methods

    private async Task<int> RemoveByPrefixRedisAsync(string prefix, CancellationToken cancellationToken)
    {
        if (Redis is null)
        {
            Logger.LogWarning("Redis not configured, falling back to in-memory removal for prefix {Prefix}", prefix);
            return await RemoveByPrefixInMemoryAsync(prefix, cancellationToken);
        }

        var removedCount = 0;
        var db = Redis.GetDatabase();
        var server = Redis.GetServers().FirstOrDefault(s => s.IsConnected && !s.IsReplica);

        if (server == null)
        {
            Logger.LogWarning("No connected Redis server found for SCAN operation");
            return await RemoveByPrefixInMemoryAsync(prefix, cancellationToken);
        }

        var pattern = $"{InstancePrefix}{prefix}*";

        try
        {
            await foreach (var key in server.KeysAsync(pattern: pattern))
            {
                if (cancellationToken.IsCancellationRequested)
                    break;

                await db.KeyDeleteAsync(key);

                var originalKey = key.ToString();
                if (originalKey.StartsWith(InstancePrefix))
                {
                    originalKey = originalKey[InstancePrefix.Length..];
                }
                _keyExpirations.TryRemove(originalKey, out _);

                removedCount++;
            }
        }
        catch (Exception ex)
        {
            Logger.LogWarning(ex, "Redis SCAN failed, falling back to in-memory tracking");
            return await RemoveByPrefixInMemoryAsync(prefix, cancellationToken);
        }

        return removedCount;
    }

    private async Task<int> RemoveByPrefixInMemoryAsync(string prefix, CancellationToken cancellationToken)
    {
        var keysToRemove = _keyExpirations.Keys
            .Where(k => k.StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
            .ToList();

        var removedCount = 0;
        foreach (var key in keysToRemove)
        {
            if (cancellationToken.IsCancellationRequested)
                break;

            try
            {
                await L2Cache.RemoveAsync(key, cancellationToken);
                _keyExpirations.TryRemove(key, out _);
                removedCount++;
            }
            catch
            {
                // Continue with other keys
            }
        }

        return removedCount;
    }

    private void TrackKey(string key, TimeSpan expiration)
    {
        var expirationTime = DateTimeOffset.UtcNow.Add(expiration);
        _keyExpirations.AddOrUpdate(key, expirationTime, (_, _) => expirationTime);

        if (_keyExpirations.Count > MaxTrackedKeys)
        {
            _ = Task.Run(() =>
            {
                try
                {
                    CleanupExpiredKeys(null);
                }
                catch (Exception ex)
                {
                    Logger.LogWarning(ex, "Cache key cleanup failed silently");
                }
            });
        }
    }

    private void CleanupLockIfUnused(string key, SemaphoreSlim keyLock)
    {
        if (_locks.Count <= MaxTrackedLocks)
            return;

        // TOCTOU FIX: Use TryRemove with value comparison for atomic check-and-remove
        if (keyLock.CurrentCount == 1)
        {
            ((ICollection<KeyValuePair<string, SemaphoreSlim>>)_locks)
                .Remove(new KeyValuePair<string, SemaphoreSlim>(key, keyLock));
        }
    }

    private void CleanupExpiredKeys(object? state)
    {
        try
        {
            var now = DateTimeOffset.UtcNow;
            var expiredKeys = _keyExpirations
                .Where(kvp => kvp.Value < now)
                .Select(kvp => kvp.Key)
                .ToList();

            foreach (var key in expiredKeys)
            {
                _keyExpirations.TryRemove(key, out _);
                L1Cache.Remove(key);
            }

            if (expiredKeys.Count > 0)
            {
                Logger.LogDebug("Cleaned up {Count} expired cache key references", expiredKeys.Count);
            }

            // LRU-like eviction if over limit
            if (_keyExpirations.Count > MaxTrackedKeys)
            {
                var keysToEvict = _keyExpirations
                    .OrderBy(kvp => kvp.Value)
                    .Take(_keyExpirations.Count - MaxTrackedKeys + 1000)
                    .Select(kvp => kvp.Key)
                    .ToList();

                foreach (var key in keysToEvict)
                {
                    _keyExpirations.TryRemove(key, out _);
                    L1Cache.Remove(key);
                }

                Logger.LogDebug("Evicted {Count} oldest cache key references to maintain limit", keysToEvict.Count);
            }

            // Cleanup unused locks
            CleanupUnusedLocks();

            // Update metrics
            Metrics.UpdateTrackedKeysCount(_keyExpirations.Count);
            Metrics.UpdateL1KeysCount(_l1KeyCount);
            Metrics.UpdateActiveLocksCount(_locks.Count);
        }
        catch (Exception ex)
        {
            Logger.LogWarning(ex, "Error during cache key cleanup");
        }
    }

    private void CleanupUnusedLocks()
    {
        if (_locks.Count <= MaxTrackedLocks / 2)
            return;

        var locksToRemove = new List<string>();

        foreach (var kvp in _locks)
        {
            if (kvp.Value.CurrentCount == 1)
            {
                locksToRemove.Add(kvp.Key);
            }
        }

        var removedCount = 0;
        foreach (var key in locksToRemove)
        {
            if (_locks.TryRemove(key, out var semaphore))
            {
                if (semaphore.CurrentCount == 1)
                {
                    semaphore.Dispose();
                    removedCount++;
                }
                else
                {
                    _locks.TryAdd(key, semaphore);
                }
            }
        }

        if (removedCount > 0)
        {
            Logger.LogDebug("Cleaned up {Count} unused cache locks", removedCount);
        }
    }

    #endregion

    public void Dispose()
    {
        Dispose(true);
        GC.SuppressFinalize(this);
    }

    protected virtual void Dispose(bool disposing)
    {
        if (_disposed) return;
        _disposed = true;

        if (disposing)
        {
            try
            {
                _cleanupTimer.Dispose();
            }
            catch
            {
                // Ignore timer disposal errors
            }

            _keyExpirations.Clear();

            foreach (var kvp in _locks)
            {
                try
                {
                    kvp.Value.Dispose();
                }
                catch
                {
                    // Ignore disposal errors
                }
            }
            _locks.Clear();
        }
    }
}
