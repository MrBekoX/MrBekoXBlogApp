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
        var (redisSettings, connectionString) = ResolveRedisConfiguration(configuration);
        services.Configure<RedisSettings>(configuration.GetSection(RedisSettings.SectionName));

        if (redisSettings.Enabled && !string.IsNullOrWhiteSpace(connectionString))
        {
            var options = BuildRedisOptions(connectionString);

            services.AddSingleton<IConnectionMultiplexer>(_ =>
                ConnectionMultiplexer.Connect(options));

            services.AddStackExchangeRedisCache(options =>
            {
                options.Configuration = connectionString;
                options.InstanceName = redisSettings.InstanceName;
            });

            services.AddScoped<IBasicCacheService, BasicRedisCacheService>();
        }
        else
        {
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
        var (redisSettings, connectionString) = ResolveRedisConfiguration(configuration);
        services.Configure<RedisSettings>(configuration.GetSection(RedisSettings.SectionName));

        services.AddMemoryCache();

        services.AddSingleton(sp =>
        {
            var meterFactory = sp.GetService<System.Diagnostics.Metrics.IMeterFactory>();
            return new CacheMetrics(meterFactory, meterName);
        });

        if (redisSettings.Enabled && !string.IsNullOrWhiteSpace(connectionString))
        {
            var options = BuildRedisOptions(connectionString);

            services.AddSingleton<IConnectionMultiplexer>(_ =>
                ConnectionMultiplexer.Connect(options));

            services.AddStackExchangeRedisCache(opts =>
            {
                opts.Configuration = connectionString;
                opts.InstanceName = redisSettings.InstanceName;
            });
        }
        else
        {
            services.AddDistributedMemoryCache();
        }

        return services;
    }

    private static (RedisSettings Settings, string? ConnectionString) ResolveRedisConfiguration(IConfiguration configuration)
    {
        var section = configuration.GetSection(RedisSettings.SectionName);
        var settings = section.Get<RedisSettings>() ?? new RedisSettings();

        var connectionString = section.Exists()
            ? settings.ConnectionString
            : configuration.GetConnectionString("Redis");

        if (string.IsNullOrWhiteSpace(connectionString))
        {
            connectionString = configuration.GetConnectionString("Redis");
        }

        if (string.IsNullOrWhiteSpace(connectionString) && !section.Exists())
        {
            settings.Enabled = false;
        }

        return (settings, connectionString);
    }

    private static ConfigurationOptions BuildRedisOptions(string connectionString)
    {
        var options = ConfigurationOptions.Parse(connectionString);
        options.ConnectRetry = 3;
        options.ReconnectRetryPolicy = new ExponentialRetry(1000);
        options.AbortOnConnectFail = false;
        options.ConnectTimeout = 10000;
        options.SyncTimeout = 5000;
        options.AsyncTimeout = 5000;
        return options;
    }
}
