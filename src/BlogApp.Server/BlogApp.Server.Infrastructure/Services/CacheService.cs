using System.Collections.Concurrent;
using System.Text.Json;
using BlogApp.Server.Application.Common.Interfaces.Services;
using MediatR;
using Microsoft.Extensions.Caching.Distributed;
using Microsoft.Extensions.Caching.Memory;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging;
using StackExchange.Redis;

namespace BlogApp.Server.Infrastructure.Services;

/// <summary>
/// Hybrid L1/L2 cache service with:
/// - L1: In-memory cache (IMemoryCache) - ultra fast, no network, short TTL
/// - L2: Distributed cache (Redis/IDistributedCache) - shared across instances, longer TTL
///
/// Features:
/// - Cache stampede protection using key-based locking
/// - SCAN-based prefix invalidation for Redis
/// - Automatic L2 to L1 promotion on cache hits
/// - Write-through: writes go to both L1 and L2
/// - Metrics for observability
/// </summary>
public class CacheService : ICacheService, IDisposable
{
    private readonly IMemoryCache _l1Cache;
    private readonly IDistributedCache _l2Cache;
    private readonly IConnectionMultiplexer? _redis;
    private readonly ILogger<CacheService> _logger;
    private readonly CacheMetrics _metrics;
    private readonly ICacheInvalidationNotifier? _notifier;
    private readonly IServiceScopeFactory? _serviceScopeFactory;
    private readonly Timer _cleanupTimer;
    private readonly ConcurrentDictionary<string, DateTimeOffset> _keyExpirations = new();
    private readonly ConcurrentDictionary<string, SemaphoreSlim> _locks = new();
    private readonly string _instancePrefix;
    private int _l1KeyCount;
    private bool _disposed;

    // L1 cache settings (short TTL for consistency across instances)
    private static readonly TimeSpan L1DefaultExpiration = TimeSpan.FromSeconds(30);
    private static readonly TimeSpan L1MaxExpiration = TimeSpan.FromMinutes(2);

    // L2 cache settings
    private static readonly TimeSpan L2DefaultExpiration = TimeSpan.FromMinutes(5);

    // General settings
    private static readonly TimeSpan CleanupInterval = TimeSpan.FromMinutes(5);
    private static readonly TimeSpan LockTimeout = TimeSpan.FromSeconds(30);
    private const int MaxTrackedKeys = 10000;
    private const int MaxTrackedLocks = 1000;

    public CacheService(
        IMemoryCache l1Cache,
        IDistributedCache l2Cache,
        ILogger<CacheService> logger,
        CacheMetrics metrics,
        ICacheInvalidationNotifier? notifier = null,
        IConnectionMultiplexer? redis = null,
        IServiceScopeFactory? serviceScopeFactory = null,
        string instancePrefix = "BlogApp_")
    {
        _l1Cache = l1Cache;
        _l2Cache = l2Cache;
        _logger = logger;
        _metrics = metrics;
        _notifier = notifier;
        _redis = redis;
        _serviceScopeFactory = serviceScopeFactory;
        _instancePrefix = instancePrefix;

        // Start periodic cleanup timer
        _cleanupTimer = new Timer(CleanupExpiredKeys, null, CleanupInterval, CleanupInterval);
    }

    public async Task<T?> GetAsync<T>(string key, CancellationToken cancellationToken = default)
    {
        using var scope = _metrics.StartOperation("get", key);
        var keyPrefix = key.GetKeyPrefix();

        try
        {
            // L1 check first (no network, ultra fast)
            if (_l1Cache.TryGetValue(key, out T? l1Value))
            {
                _metrics.RecordL1Hit(keyPrefix);
                _logger.LogDebug("L1 cache hit for key {Key}", key);
                return l1Value;
            }

            _metrics.RecordL1Miss(keyPrefix);

            // L2 check (Redis/distributed cache)
            var l2Data = await _l2Cache.GetStringAsync(key, cancellationToken);

            if (string.IsNullOrEmpty(l2Data))
            {
                _metrics.RecordL2Miss(keyPrefix);
                _keyExpirations.TryRemove(key, out _);
                return default;
            }

            _metrics.RecordL2Hit(keyPrefix);

            // Deserialize and promote to L1
            var value = JsonSerializer.Deserialize<T>(l2Data);
            if (value is not null)
            {
                PromoteToL1(key, value);
                _metrics.RecordL1Promotion(keyPrefix);
            }

            return value;
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Error getting cache key {Key}", key);
            _metrics.RecordError("get", keyPrefix);
            return default;
        }
    }

    public async Task SetAsync<T>(string key, T value, TimeSpan? expiration = null, CancellationToken cancellationToken = default)
    {
        using var scope = _metrics.StartOperation("set", key);
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
            await _l2Cache.SetStringAsync(key, data, options, cancellationToken);

            // Track key with expiration time for cleanup
            TrackKey(key, l2Expiration);
            _metrics.RecordWrite(keyPrefix);

            _logger.LogDebug("Cache set for key {Key} (L1: {L1TTL}s, L2: {L2TTL}s)",
                key, l1Expiration.TotalSeconds, l2Expiration.TotalSeconds);
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Error setting cache key {Key}", key);
            _metrics.RecordError("set", keyPrefix);
        }
    }

    public async Task RemoveAsync(string key, CancellationToken cancellationToken = default)
    {
        using var scope = _metrics.StartOperation("remove", key);
        var keyPrefix = key.GetKeyPrefix();

        try
        {
            // Remove from both layers
            _l1Cache.Remove(key);
            Interlocked.Decrement(ref _l1KeyCount);

            await _l2Cache.RemoveAsync(key, cancellationToken);
            _keyExpirations.TryRemove(key, out _);

            _metrics.RecordRemoval(keyPrefix);
            _logger.LogDebug("Cache removed for key {Key}", key);

            // Notify frontend clients about cache invalidation
            if (_notifier != null)
            {
                _ = _notifier.NotifyKeyRemovedAsync(key, CancellationToken.None);
            }
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Error removing cache key {Key}", key);
            _metrics.RecordError("remove", keyPrefix);
        }
    }

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
                _l1Cache.Remove(key);
                Interlocked.Decrement(ref _l1KeyCount);
            }

            // Remove from L2
            if (_redis != null && _redis.IsConnected)
            {
                removedCount = await RemoveByPrefixRedisAsync(prefix, cancellationToken);
            }
            else
            {
                removedCount = await RemoveByPrefixInMemoryAsync(prefix, cancellationToken);
            }

            _logger.LogDebug("Removed {Count} cache keys with prefix: {Prefix}", removedCount, prefix);

            // Notify frontend clients about cache invalidation
            if (_notifier != null && removedCount > 0)
            {
                _ = _notifier.NotifyPrefixRemovedAsync(prefix, CancellationToken.None);
            }
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Error removing cache keys with prefix {Prefix}", prefix);
        }
    }

    /// <summary>
    /// Gets a value from cache or creates it using the factory function.
    /// Implements cache stampede protection using key-based locking with double-check pattern.
    /// Uses L1/L2 hybrid caching for optimal performance.
    /// </summary>
    public async Task<T> GetOrSetAsync<T>(string key, Func<Task<T>> factory, TimeSpan? expiration = null, CancellationToken cancellationToken = default)
    {
        using var scope = _metrics.StartOperation("get_or_set", key);
        var keyPrefix = key.GetKeyPrefix();

        // First check - L1 (no lock needed, ultra fast)
        if (_l1Cache.TryGetValue(key, out T? l1Value))
        {
            _metrics.RecordL1Hit(keyPrefix);
            return l1Value!;
        }

        _metrics.RecordL1Miss(keyPrefix);

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
                _logger.LogWarning("Lock timeout for cache key {Key}, executing factory without lock", key);
                _metrics.RecordLockTimeout(keyPrefix);

                // Fallback: execute factory without lock (better than hanging)
                var fallbackValue = await factory();
                await SetAsync(key, fallbackValue, expiration, cancellationToken);
                return fallbackValue;
            }

            // Double-check L1 after acquiring lock
            if (_l1Cache.TryGetValue(key, out l1Value))
            {
                _logger.LogDebug("L1 cache hit after lock for key {Key} (stampede prevented)", key);
                _metrics.RecordStampedePrevented(keyPrefix);
                _metrics.RecordL1Hit(keyPrefix);
                return l1Value!;
            }

            // Double-check L2 after acquiring lock
            cached = await GetFromL2Async<T>(key, keyPrefix, cancellationToken);
            if (cached is not null)
            {
                _logger.LogDebug("L2 cache hit after lock for key {Key} (stampede prevented)", key);
                _metrics.RecordStampedePrevented(keyPrefix);
                return cached;
            }

            // We're the first one - execute factory and cache the result
            _logger.LogDebug("Executing factory for cache key {Key}", key);
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

    public async Task<bool> ExistsAsync(string key, CancellationToken cancellationToken = default)
    {
        try
        {
            // Check L1 first
            if (_l1Cache.TryGetValue(key, out _))
                return true;

            // Check L2
            var data = await _l2Cache.GetStringAsync(key, cancellationToken);
            var exists = !string.IsNullOrEmpty(data);

            if (!exists)
            {
                _keyExpirations.TryRemove(key, out _);
            }

            return exists;
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Error checking cache key {Key}", key);
            return false;
        }
    }

    public async Task<long> GetGroupVersionAsync(string groupName, CancellationToken cancellationToken = default)
    {
        var versionKey = $"cache_version:{groupName}";

        try
        {
            // Redis path (preferred for atomic operations)
            if (_redis?.IsConnected == true)
            {
                var db = _redis.GetDatabase();
                var value = await db.StringGetAsync(versionKey);

                if (value.HasValue && long.TryParse(value.ToString(), out var v))
                    return v;

                return 1;
            }

            // Fallback: distributed cache
            var data = await _l2Cache.GetStringAsync(versionKey, cancellationToken);

            if (!string.IsNullOrWhiteSpace(data) && long.TryParse(data, out var v2))
                return v2;

            return 1;
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Error getting cache group version for {GroupName}, returning default", groupName);
            return 1;
        }
    }

    public async Task RotateGroupVersionAsync(string groupName, CancellationToken cancellationToken = default)
    {
        var versionKey = $"cache_version:{groupName}";

        try
        {
            // Redis path: atomic INCR
            if (_redis != null && _redis.IsConnected)
            {
                var db = _redis.GetDatabase();
                var newVersion = await db.StringIncrementAsync(versionKey);
                _logger.LogDebug("Rotated cache version for group {GroupName} to {Version}", groupName, newVersion);

                // Clear L1 cache for this group (approximate - clear all tracked keys with group prefix)
                ClearL1ByPrefix($"{groupName}:");

                // Notify frontend clients about cache group invalidation
                if (_notifier != null)
                {
                    _ = _notifier.NotifyGroupInvalidatedAsync(groupName, CancellationToken.None);
                }
                return;
            }

            // Fallback: get + set (not atomic but works for single instance)
            var currentVersion = await GetGroupVersionAsync(groupName, cancellationToken);
            var newVersionFallback = currentVersion + 1;

            var options = new DistributedCacheEntryOptions
            {
                AbsoluteExpirationRelativeToNow = TimeSpan.FromDays(365)
            };

            await _l2Cache.SetStringAsync(versionKey, newVersionFallback.ToString(), options, cancellationToken);
            _logger.LogDebug("Rotated cache version for group {GroupName} to {Version} (fallback mode)", groupName, newVersionFallback);

            ClearL1ByPrefix($"{groupName}:");

            // Notify frontend clients about cache group invalidation
            if (_notifier != null)
            {
                _ = _notifier.NotifyGroupInvalidatedAsync(groupName, CancellationToken.None);
            }
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Error rotating cache group version for {GroupName}", groupName);
        }
    }

    #region Private Helper Methods

    private async Task<T?> GetFromL2Async<T>(string key, string keyPrefix, CancellationToken cancellationToken)
    {
        var l2Data = await _l2Cache.GetStringAsync(key, cancellationToken);

        if (string.IsNullOrEmpty(l2Data))
        {
            _metrics.RecordL2Miss(keyPrefix);
            return default;
        }

        _metrics.RecordL2Hit(keyPrefix);

        var value = JsonSerializer.Deserialize<T>(l2Data);
        if (value is not null)
        {
            PromoteToL1(key, value);
            _metrics.RecordL1Promotion(keyPrefix);
        }

        return value;
    }

    private void SetL1<T>(string key, T value, TimeSpan expiration)
    {
        var options = new MemoryCacheEntryOptions
        {
            AbsoluteExpirationRelativeToNow = expiration
        };

        // Track eviction
        options.RegisterPostEvictionCallback((evictedKey, _, _, _) =>
        {
            Interlocked.Decrement(ref _l1KeyCount);
            _logger.LogDebug("L1 cache evicted key {Key}", evictedKey);
        });

        _l1Cache.Set(key, value, options);
        Interlocked.Increment(ref _l1KeyCount);
    }

    private void PromoteToL1<T>(string key, T value)
    {
        // Promote with default L1 TTL
        SetL1(key, value, L1DefaultExpiration);
    }

    private static TimeSpan CalculateL1Expiration(TimeSpan l2Expiration)
    {
        // L1 TTL is 1/10th of L2 TTL, capped between 10 seconds and 2 minutes
        var l1Ttl = TimeSpan.FromTicks(l2Expiration.Ticks / 10);

        if (l1Ttl < TimeSpan.FromSeconds(10))
            return TimeSpan.FromSeconds(10);

        if (l1Ttl > L1MaxExpiration)
            return L1MaxExpiration;

        return l1Ttl;
    }

    private void ClearL1ByPrefix(string prefix)
    {
        var keysToRemove = _keyExpirations.Keys
            .Where(k => k.StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
            .ToList();

        foreach (var key in keysToRemove)
        {
            _l1Cache.Remove(key);
            Interlocked.Decrement(ref _l1KeyCount);
        }

        if (keysToRemove.Count > 0)
        {
            _logger.LogDebug("Cleared {Count} L1 cache entries with prefix {Prefix}", keysToRemove.Count, prefix);
        }
    }

    private async Task<int> RemoveByPrefixRedisAsync(string prefix, CancellationToken cancellationToken)
    {
        var removedCount = 0;
        var db = _redis!.GetDatabase();
        var server = _redis.GetServers().FirstOrDefault(s => s.IsConnected && !s.IsReplica);

        if (server == null)
        {
            _logger.LogWarning("No connected Redis server found for SCAN operation");
            return await RemoveByPrefixInMemoryAsync(prefix, cancellationToken);
        }

        var pattern = $"{_instancePrefix}{prefix}*";

        try
        {
            await foreach (var key in server.KeysAsync(pattern: pattern))
            {
                if (cancellationToken.IsCancellationRequested)
                    break;

                await db.KeyDeleteAsync(key);

                var originalKey = key.ToString();
                if (originalKey.StartsWith(_instancePrefix))
                {
                    originalKey = originalKey[_instancePrefix.Length..];
                }
                _keyExpirations.TryRemove(originalKey, out _);

                removedCount++;
            }
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Redis SCAN failed, falling back to in-memory tracking");
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
                await _l2Cache.RemoveAsync(key, cancellationToken);
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
            Task.Run(() => CleanupExpiredKeys(null));
        }
    }

    private void CleanupLockIfUnused(string key, SemaphoreSlim keyLock)
    {
        if (_locks.Count <= MaxTrackedLocks)
            return;

        // TOCTOU FIX: Use TryRemove with value comparison for atomic check-and-remove
        // Only remove if the lock is both available (CurrentCount == 1) and still the same instance
        if (keyLock.CurrentCount == 1)
        {
            // Atomic remove only if value matches - prevents TOCTOU where lock could be reacquired
            // between CurrentCount check and TryRemove
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
                _l1Cache.Remove(key);
            }

            if (expiredKeys.Count > 0)
            {
                _logger.LogDebug("Cleaned up {Count} expired cache key references", expiredKeys.Count);
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
                    _l1Cache.Remove(key);
                }

                _logger.LogDebug("Evicted {Count} oldest cache key references to maintain limit", keysToEvict.Count);
            }

            // Cleanup unused locks
            CleanupUnusedLocks();

            // Update metrics
            _metrics.UpdateTrackedKeysCount(_keyExpirations.Count);
            _metrics.UpdateL1KeysCount(_l1KeyCount);
            _metrics.UpdateActiveLocksCount(_locks.Count);
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Error during cache key cleanup");
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
            _logger.LogDebug("Cleaned up {Count} unused cache locks", removedCount);
        }
    }

    #endregion

    #region Stale-While-Revalidate (SWR) Implementation

    /// <summary>
    /// Wrapper class for cache entries with SWR metadata.
    /// </summary>
    private sealed record SwrCacheEntry<T>(T Value, DateTimeOffset SoftExpiration);

    /// <summary>
    /// Key suffix for storing SWR metadata.
    /// </summary>
    private const string SwrMetadataSuffix = ":swr_meta";

    public async Task SetWithSoftExpirationAsync<T>(
        string key,
        T value,
        TimeSpan softExpiration,
        TimeSpan hardExpiration,
        CancellationToken cancellationToken = default)
    {
        using var scope = _metrics.StartOperation("set_swr", key);
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
            await _l2Cache.SetStringAsync(key, data, options, cancellationToken);

            TrackKey(key, hardExpiration);
            _metrics.RecordWrite(keyPrefix);

            _logger.LogDebug(
                "SWR cache set for key {Key} (soft: {SoftTTL}s, hard: {HardTTL}s)",
                key, softExpiration.TotalSeconds, hardExpiration.TotalSeconds);
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Error setting SWR cache key {Key}", key);
            _metrics.RecordError("set_swr", keyPrefix);
        }
    }

    public async Task<CacheResult<T>> GetWithMetadataAsync<T>(string key, CancellationToken cancellationToken = default)
    {
        using var scope = _metrics.StartOperation("get_swr", key);
        var keyPrefix = key.GetKeyPrefix();

        try
        {
            // Check L1 first
            if (_l1Cache.TryGetValue(key, out SwrCacheEntry<T>? l1Entry) && l1Entry is not null)
            {
                _metrics.RecordL1Hit(keyPrefix);
                var isStale = DateTimeOffset.UtcNow > l1Entry.SoftExpiration;

                if (isStale)
                    _metrics.RecordSwrStaleHit(keyPrefix);
                else
                    _metrics.RecordSwrFreshHit(keyPrefix);

                return new CacheResult<T>(l1Entry.Value, isStale, true);
            }

            _metrics.RecordL1Miss(keyPrefix);

            // Check L2
            var l2Data = await _l2Cache.GetStringAsync(key, cancellationToken);

            if (string.IsNullOrEmpty(l2Data))
            {
                _metrics.RecordL2Miss(keyPrefix);
                return new CacheResult<T>(default, false, false);
            }

            _metrics.RecordL2Hit(keyPrefix);

            var entry = JsonSerializer.Deserialize<SwrCacheEntry<T>>(l2Data);
            if (entry is null)
            {
                return new CacheResult<T>(default, false, false);
            }

            // Promote to L1
            PromoteToL1(key, entry);
            _metrics.RecordL1Promotion(keyPrefix);

            var stale = DateTimeOffset.UtcNow > entry.SoftExpiration;

            if (stale)
                _metrics.RecordSwrStaleHit(keyPrefix);
            else
                _metrics.RecordSwrFreshHit(keyPrefix);

            return new CacheResult<T>(entry.Value, stale, true);
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Error getting SWR cache key {Key}", key);
            _metrics.RecordError("get_swr", keyPrefix);
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
        using var scope = _metrics.StartOperation("get_or_set_swr", key);
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
                _logger.LogDebug("SWR: Returning stale value for {Key}, triggering background refresh", key);
                _metrics.RecordSwrBackgroundRefresh(keyPrefix);

                // Fire-and-forget background refresh
                _ = Task.Run(async () =>
                {
                    try
                    {
                        var freshValue = await factory();
                        await SetWithSoftExpirationAsync(key, freshValue, softExpiration, actualHardExpiration, CancellationToken.None);
                        _logger.LogDebug("SWR: Background refresh completed for {Key}", key);
                    }
                    catch (Exception ex)
                    {
                        _logger.LogWarning(ex, "SWR: Background refresh failed for {Key}", key);
                        _metrics.RecordSwrBackgroundRefreshError(keyPrefix);
                    }
                }, CancellationToken.None);

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
                _logger.LogWarning("SWR: Lock timeout for cache key {Key}, executing factory without lock", key);
                _metrics.RecordLockTimeout(keyPrefix);

                var fallbackValue = await factory();
                await SetWithSoftExpirationAsync(key, fallbackValue, softExpiration, actualHardExpiration, cancellationToken);
                return fallbackValue;
            }

            // Double-check after acquiring lock
            result = await GetWithMetadataAsync<T>(key, cancellationToken);

            if (result.IsHit)
            {
                _metrics.RecordStampedePrevented(keyPrefix);

                if (result.IsStale)
                {
                    // Another request got the lock but the value is still stale
                    // We have the lock, so we'll do the refresh synchronously
                    _logger.LogDebug("SWR: Stale hit after lock for {Key}, refreshing synchronously", key);
                    var freshValue = await factory();
                    await SetWithSoftExpirationAsync(key, freshValue, softExpiration, actualHardExpiration, cancellationToken);
                    return freshValue;
                }

                return result.Value!;
            }

            // Execute factory and cache result
            _logger.LogDebug("SWR: Cache miss for {Key}, executing factory", key);
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
        using var scope = _metrics.StartOperation("get_or_set_swr_scoped", key);
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
                _logger.LogDebug("SWR (scoped): Returning stale value for {Key}, triggering background refresh", key);
                _metrics.RecordSwrBackgroundRefresh(keyPrefix);

                // Fire-and-forget background refresh with new DI scope
                _ = Task.Run(async () =>
                {
                    try
                    {
                        if (_serviceScopeFactory == null)
                        {
                            _logger.LogWarning("SWR: IServiceScopeFactory not available, cannot perform background refresh for {Key}", key);
                            return;
                        }

                        // Create a new DI scope for background work
                        using var backgroundScope = _serviceScopeFactory.CreateScope();
                        var mediator = backgroundScope.ServiceProvider.GetRequiredService<IMediator>();

                        // Re-execute the request with fresh services
                        var freshValue = await mediator.Send(request, CancellationToken.None);

                        if (freshValue is TResponse typedResponse)
                        {
                            await SetWithSoftExpirationAsync(key, typedResponse, softExpiration, actualHardExpiration, CancellationToken.None);
                            _logger.LogDebug("SWR (scoped): Background refresh completed for {Key}", key);
                        }
                    }
                    catch (Exception ex)
                    {
                        _logger.LogWarning(ex, "SWR (scoped): Background refresh failed for {Key}", key);
                        _metrics.RecordSwrBackgroundRefreshError(keyPrefix);
                    }
                }, CancellationToken.None);

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
                _logger.LogWarning("SWR (scoped): Lock timeout for cache key {Key}, executing factory without lock", key);
                _metrics.RecordLockTimeout(keyPrefix);

                var fallbackValue = await factory();
                await SetWithSoftExpirationAsync(key, fallbackValue, softExpiration, actualHardExpiration, cancellationToken);
                return fallbackValue;
            }

            // Double-check after acquiring lock
            result = await GetWithMetadataAsync<TResponse>(key, cancellationToken);

            if (result.IsHit)
            {
                _metrics.RecordStampedePrevented(keyPrefix);

                if (result.IsStale)
                {
                    // Another request got the lock but the value is still stale
                    // We have the lock, so we'll do the refresh synchronously
                    _logger.LogDebug("SWR (scoped): Stale hit after lock for {Key}, refreshing synchronously", key);
                    var freshValue = await factory();
                    await SetWithSoftExpirationAsync(key, freshValue, softExpiration, actualHardExpiration, cancellationToken);
                    return freshValue;
                }

                return result.Value!;
            }

            // Execute factory and cache result
            _logger.LogDebug("SWR (scoped): Cache miss for {Key}, executing factory", key);
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

    public void Dispose()
    {
        if (_disposed) return;

        _cleanupTimer.Dispose();
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

        _disposed = true;
        GC.SuppressFinalize(this);
    }
}
