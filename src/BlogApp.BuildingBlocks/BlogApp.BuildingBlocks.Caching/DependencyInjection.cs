using BlogApp.BuildingBlocks.Caching.Abstractions;
using BlogApp.BuildingBlocks.Caching.Metrics;
using BlogApp.BuildingBlocks.Caching.Options;
using BlogApp.BuildingBlocks.Caching.Redis;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using StackExchange.Redis;

namespace BlogApp.BuildingBlocks.Caching;

/// <summary>
/// Dependency injection extensions for caching services
/// </summary>
public static class DependencyInjection
{
    /// <summary>
    /// Add basic caching services to the service collection.
    /// Configures Redis distributed cache with retry policy and registers IBasicCacheService.
    /// </summary>
    public static IServiceCollection AddBasicCachingServices(this IServiceCollection services, IConfiguration configuration)
    {
        // Configure Redis settings
        services.Configure<RedisSettings>(configuration.GetSection(RedisSettings.SectionName));

        var redisSettings = configuration.GetSection(RedisSettings.SectionName).Get<RedisSettings>();
        var connectionString = redisSettings?.ConnectionString
                               ?? configuration.GetConnectionString("Redis");

        if (redisSettings?.Enabled == true && !string.IsNullOrEmpty(connectionString))
        {
            // Configure Redis connection with retry policy
            var options = ConfigurationOptions.Parse(connectionString);
            options.ConnectRetry = 3; // Number of retry attempts
            options.ReconnectRetryPolicy = new ExponentialRetry(1000); // Start with 1 second delay
            options.AbortOnConnectFail = false; // Don't abort on initial connection failure
            options.ConnectTimeout = 10000; // 10 seconds connection timeout
            options.SyncTimeout = 5000; // 5 seconds sync timeout
            options.AsyncTimeout = 5000; // 5 seconds async timeout

            // Register Redis connection multiplexer as singleton with retry policy
            services.AddSingleton<IConnectionMultiplexer>(_ =>
                ConnectionMultiplexer.Connect(options));

            // Register Redis distributed cache
            services.AddStackExchangeRedisCache(options =>
            {
                options.Configuration = connectionString;
                options.InstanceName = redisSettings.InstanceName;
            });

            // Register basic cache service
            services.AddScoped<IBasicCacheService, BasicRedisCacheService>();
        }
        else
        {
            // Fallback to in-memory cache when Redis is disabled
            services.AddDistributedMemoryCache();
            services.AddScoped<IBasicCacheService, BasicRedisCacheService>();
        }

        return services;
    }

    /// <summary>
    /// Add hybrid caching infrastructure services (Redis connection, metrics, memory cache).
    /// Does NOT register IHybridCacheService - that should be done by the consuming application
    /// with its domain-specific implementation.
    /// </summary>
    public static IServiceCollection AddHybridCachingInfrastructure(
        this IServiceCollection services,
        IConfiguration configuration,
        string? meterName = null)
    {
        // Configure Redis settings
        services.Configure<RedisSettings>(configuration.GetSection(RedisSettings.SectionName));

        var redisSettings = configuration.GetSection(RedisSettings.SectionName).Get<RedisSettings>();
        var connectionString = redisSettings?.ConnectionString
                               ?? configuration.GetConnectionString("Redis");

        // Register memory cache for L1
        services.AddMemoryCache();

        // Register cache metrics
        services.AddSingleton(sp =>
        {
            var meterFactory = sp.GetService<System.Diagnostics.Metrics.IMeterFactory>();
            return new CacheMetrics(meterFactory, meterName);
        });

        if (redisSettings?.Enabled == true && !string.IsNullOrEmpty(connectionString))
        {
            // Configure Redis connection with retry policy
            var options = ConfigurationOptions.Parse(connectionString);
            options.ConnectRetry = 3;
            options.ReconnectRetryPolicy = new ExponentialRetry(1000);
            options.AbortOnConnectFail = false;
            options.ConnectTimeout = 10000;
            options.SyncTimeout = 5000;
            options.AsyncTimeout = 5000;

            // Register Redis connection multiplexer as singleton
            services.AddSingleton<IConnectionMultiplexer>(_ =>
                ConnectionMultiplexer.Connect(options));

            // Register Redis distributed cache for L2
            services.AddStackExchangeRedisCache(opts =>
            {
                opts.Configuration = connectionString;
                opts.InstanceName = redisSettings.InstanceName;
            });
        }
        else
        {
            // Fallback to in-memory distributed cache when Redis is disabled
            services.AddDistributedMemoryCache();
        }

        return services;
    }
}
