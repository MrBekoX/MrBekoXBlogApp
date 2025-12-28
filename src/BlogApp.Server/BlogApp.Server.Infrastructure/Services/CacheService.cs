using System.Collections.Concurrent;
using System.Text.Json;
using BlogApp.Server.Application.Common.Interfaces;
using Microsoft.Extensions.Caching.Distributed;
using Microsoft.Extensions.Logging;

namespace BlogApp.Server.Infrastructure.Services;

/// <summary>
/// Redis/Distributed Cache service with memory-safe key tracking.
/// Uses LRU eviction and automatic cleanup to prevent memory leaks.
/// </summary>
public class CacheService : ICacheService, IDisposable
{
    private readonly IDistributedCache _cache;
    private readonly ILogger<CacheService> _logger;
    private readonly Timer _cleanupTimer;
    private readonly ConcurrentDictionary<string, DateTimeOffset> _keyExpirations = new();
    private bool _disposed;

    private static readonly TimeSpan DefaultExpiration = TimeSpan.FromMinutes(5);
    private static readonly TimeSpan CleanupInterval = TimeSpan.FromMinutes(5);
    private const int MaxTrackedKeys = 10000;

    public CacheService(IDistributedCache cache, ILogger<CacheService> logger)
    {
        _cache = cache;
        _logger = logger;

        // Start periodic cleanup timer
        _cleanupTimer = new Timer(CleanupExpiredKeys, null, CleanupInterval, CleanupInterval);
    }

    public async Task<T?> GetAsync<T>(string key, CancellationToken cancellationToken = default)
    {
        try
        {
            var data = await _cache.GetStringAsync(key, cancellationToken);

            if (string.IsNullOrEmpty(data))
            {
                // Key doesn't exist in cache, remove from tracking
                _keyExpirations.TryRemove(key, out _);
                return default;
            }

            return JsonSerializer.Deserialize<T>(data);
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Error getting cache key {Key}", key);
            return default;
        }
    }

    public async Task SetAsync<T>(string key, T value, TimeSpan? expiration = null, CancellationToken cancellationToken = default)
    {
        try
        {
            var actualExpiration = expiration ?? DefaultExpiration;
            var options = new DistributedCacheEntryOptions
            {
                AbsoluteExpirationRelativeToNow = actualExpiration
            };

            var data = JsonSerializer.Serialize(value);
            await _cache.SetStringAsync(key, data, options, cancellationToken);

            // Track key with expiration time for cleanup
            TrackKey(key, actualExpiration);
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Error setting cache key {Key}", key);
        }
    }

    public async Task RemoveAsync(string key, CancellationToken cancellationToken = default)
    {
        try
        {
            await _cache.RemoveAsync(key, cancellationToken);
            _keyExpirations.TryRemove(key, out _);
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Error removing cache key {Key}", key);
        }
    }

    public async Task RemoveByPrefixAsync(string prefix, CancellationToken cancellationToken = default)
    {
        try
        {
            var keysToRemove = _keyExpirations.Keys
                .Where(k => k.StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
                .ToList();

            var removedCount = 0;
            foreach (var key in keysToRemove)
            {
                try
                {
                    await _cache.RemoveAsync(key, cancellationToken);
                    _keyExpirations.TryRemove(key, out _);
                    removedCount++;
                }
                catch
                {
                    // Continue with other keys even if one fails
                }
            }

            _logger.LogDebug("Removed {Count} cache keys with prefix: {Prefix}", removedCount, prefix);
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Error removing cache keys with prefix {Prefix}", prefix);
        }
    }

    public async Task<bool> ExistsAsync(string key, CancellationToken cancellationToken = default)
    {
        try
        {
            var data = await _cache.GetStringAsync(key, cancellationToken);
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

    public async Task<T> GetOrSetAsync<T>(string key, Func<Task<T>> factory, TimeSpan? expiration = null, CancellationToken cancellationToken = default)
    {
        var cached = await GetAsync<T>(key, cancellationToken);

        if (cached is not null)
            return cached;

        var value = await factory();
        await SetAsync(key, value, expiration, cancellationToken);

        return value;
    }

    private void TrackKey(string key, TimeSpan expiration)
    {
        var expirationTime = DateTimeOffset.UtcNow.Add(expiration);

        // Update or add the key
        _keyExpirations.AddOrUpdate(key, expirationTime, (_, _) => expirationTime);

        // If we exceed max keys, trigger cleanup
        if (_keyExpirations.Count > MaxTrackedKeys)
        {
            Task.Run(() => CleanupExpiredKeys(null));
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
            }

            if (expiredKeys.Count > 0)
            {
                _logger.LogDebug("Cleaned up {Count} expired cache key references", expiredKeys.Count);
            }

            // If still over limit, remove oldest keys (LRU-like behavior)
            if (_keyExpirations.Count > MaxTrackedKeys)
            {
                var keysToEvict = _keyExpirations
                    .OrderBy(kvp => kvp.Value)
                    .Take(_keyExpirations.Count - MaxTrackedKeys + 1000) // Remove extra to avoid frequent cleanups
                    .Select(kvp => kvp.Key)
                    .ToList();

                foreach (var key in keysToEvict)
                {
                    _keyExpirations.TryRemove(key, out _);
                }

                _logger.LogDebug("Evicted {Count} oldest cache key references to maintain limit", keysToEvict.Count);
            }
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Error during cache key cleanup");
        }
    }

    public void Dispose()
    {
        if (_disposed) return;

        _cleanupTimer.Dispose();
        _keyExpirations.Clear();
        _disposed = true;

        GC.SuppressFinalize(this);
    }
}
