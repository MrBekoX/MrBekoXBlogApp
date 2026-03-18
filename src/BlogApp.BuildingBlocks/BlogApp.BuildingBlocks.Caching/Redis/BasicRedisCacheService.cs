using System.Text.Json;
using BlogApp.BuildingBlocks.Caching.Abstractions;
using BlogApp.BuildingBlocks.Caching.Options;
using Microsoft.Extensions.Caching.Distributed;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;

namespace BlogApp.BuildingBlocks.Caching.Redis;

/// <summary>
/// Exception thrown when JSON deserialization fails in cache operations.
/// </summary>
public class CacheSerializationException : Exception
{
    public CacheSerializationException(string message, Exception? innerException = null)
        : base(message, innerException) { }
}

/// <summary>
/// Basic Redis cache service implementation.
/// Provides simple get/set/remove operations without advanced features.
/// </summary>
public class BasicRedisCacheService : IBasicCacheService
{
    private readonly IDistributedCache _cache;
    private readonly RedisSettings _settings;
    private readonly ILogger<BasicRedisCacheService> _logger;
    private readonly JsonSerializerOptions _jsonOptions;

    public BasicRedisCacheService(
        IDistributedCache cache,
        IOptions<RedisSettings> settings,
        ILogger<BasicRedisCacheService> logger)
    {
        _cache = cache;
        _settings = settings.Value;
        _logger = logger;
        _jsonOptions = new JsonSerializerOptions
        {
            PropertyNamingPolicy = JsonNamingPolicy.CamelCase
        };
    }

    public async Task<T?> GetAsync<T>(string key, CancellationToken cancellationToken = default)
    {
        try
        {
            var data = await _cache.GetStringAsync(key, cancellationToken);
            if (string.IsNullOrEmpty(data))
                return default;

            return JsonSerializer.Deserialize<T>(data, _jsonOptions);
        }
        catch (JsonException ex)
        {
            // Fix: Re-throw JsonException instead of returning default
            // This prevents null references downstream when deserialization fails
            _logger.LogError(ex, "JSON deserialization failed for cache key: {Key}", key);
            throw new CacheSerializationException($"Failed to deserialize cache key '{key}'", ex);
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Failed to get cache key: {Key}", key);
            return default;
        }
    }

    public async Task SetAsync<T>(string key, T value, TimeSpan? expiration = null, CancellationToken cancellationToken = default)
    {
        try
        {
            var json = JsonSerializer.Serialize(value, _jsonOptions);
            var options = new DistributedCacheEntryOptions
            {
                AbsoluteExpirationRelativeToNow = expiration ?? TimeSpan.FromMinutes(_settings.DefaultExpirationMinutes)
            };

            await _cache.SetStringAsync(key, json, options, cancellationToken);
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Failed to set cache key: {Key}", key);
        }
    }

    public async Task RemoveAsync(string key, CancellationToken cancellationToken = default)
    {
        try
        {
            await _cache.RemoveAsync(key, cancellationToken);
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Failed to remove cache key: {Key}", key);
        }
    }

    public async Task<bool> ExistsAsync(string key, CancellationToken cancellationToken = default)
    {
        try
        {
            var data = await _cache.GetAsync(key, cancellationToken);
            return data != null;
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Failed to check cache key: {Key}", key);
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
}
