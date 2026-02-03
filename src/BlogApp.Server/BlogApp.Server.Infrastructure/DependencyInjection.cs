using BlogApp.BuildingBlocks.Caching.Abstractions;
using BlogApp.BuildingBlocks.Caching.Metrics;
using BlogApp.BuildingBlocks.Caching.Options;
using BlogApp.BuildingBlocks.Messaging;
using BlogApp.Server.Application.Common.Interfaces.Data;
using BlogApp.Server.Application.Common.Interfaces.Persistence;
using BlogApp.Server.Application.Common.Interfaces.Persistence.BlogPostRepository;
using BlogApp.Server.Application.Common.Interfaces.Persistence.CategoryRepository;
using BlogApp.Server.Application.Common.Interfaces.Persistence.CommentRepository;
using BlogApp.Server.Application.Common.Interfaces.Persistence.RefreshTokenRepository;
using BlogApp.Server.Application.Common.Interfaces.Persistence.TagRepository;
using BlogApp.Server.Application.Common.Interfaces.Persistence.UserRepository;
using BlogApp.Server.Application.Common.Interfaces.Services;
using BlogApp.Server.Application.Common.Options;
using BlogApp.Server.Infrastructure.Persistence;
using BlogApp.Server.Infrastructure.Persistence.Repositories;
using BlogApp.Server.Infrastructure.Persistence.Repositories.EfCoreBlogPostRepository;
using BlogApp.Server.Infrastructure.Persistence.Repositories.EfCoreCategoryRepository;
using BlogApp.Server.Infrastructure.Persistence.Repositories.EfCoreCommentRepository;
using BlogApp.Server.Infrastructure.Persistence.Repositories.EfCoreRefreshTokenRepository;
using BlogApp.Server.Infrastructure.Persistence.Repositories.EfCoreTagRepository;
using BlogApp.Server.Infrastructure.Persistence.Repositories.EfCoreUserRepository;
using BlogApp.Server.Infrastructure.Services;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Diagnostics;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;

namespace BlogApp.Server.Infrastructure;

/// <summary>
/// Infrastructure katmanı dependency injection
/// </summary>
public static class DependencyInjection
{
    public static IServiceCollection AddInfrastructureServices(this IServiceCollection services, IConfiguration configuration)
    {
        // Options Pattern Configuration
        services.Configure<JwtSettings>(configuration.GetSection(JwtSettings.SectionName));
        services.Configure<AdminUserSettings>(configuration.GetSection(AdminUserSettings.SectionName));

        // SiteSettings için CorsOrigins array'ini özel olarak bağla
        services.Configure<SiteSettings>(options =>
        {
            var origins = configuration.GetSection("CorsOrigins").Get<string[]>();
            options.Origins = origins ?? ["http://localhost:3000"];
        });

        // Database
        var connectionString = configuration.GetConnectionString("DefaultConnection")
            ?? throw new InvalidOperationException(
                "Connection string 'DefaultConnection' not found. " +
                "Please ensure it is configured in appsettings.json or environment variables.");
        services.AddDbContext<AppDbContext>(options =>
        {
            options.UseNpgsql(connectionString, npgsqlOptions =>
            {
                npgsqlOptions.MigrationsAssembly(typeof(AppDbContext).Assembly.FullName);
                npgsqlOptions.EnableRetryOnFailure(3);
            });
            
            // Suppress PendingModelChangesWarning - we handle migrations manually via SQL scripts
            options.ConfigureWarnings(warnings =>
                warnings.Ignore(RelationalEventId.PendingModelChangesWarning));
        });

        services.AddScoped<IApplicationDbContext>(provider =>
            provider.GetRequiredService<AppDbContext>());

        // Redis Cache Configuration (using BuildingBlocks shared settings)
        services.Configure<RedisSettings>(configuration.GetSection(RedisSettings.SectionName));
        
        var redisSettings = configuration.GetSection(RedisSettings.SectionName).Get<RedisSettings>();
        var redisConnectionString = redisSettings?.ConnectionString 
                                    ?? configuration.GetConnectionString("Redis");
        
        if (redisSettings?.Enabled == true && !string.IsNullOrEmpty(redisConnectionString))
        {
            // Configure Redis connection with retry policy
            var options = StackExchange.Redis.ConfigurationOptions.Parse(redisConnectionString);
            options.ConnectRetry = 3;
            options.ReconnectRetryPolicy = new StackExchange.Redis.ExponentialRetry(1000);
            options.AbortOnConnectFail = false;
            options.ConnectTimeout = 10000;
            options.SyncTimeout = 5000;
            options.AsyncTimeout = 5000;

            services.AddSingleton<StackExchange.Redis.IConnectionMultiplexer>(_ =>
                StackExchange.Redis.ConnectionMultiplexer.Connect(options));
            
            services.AddStackExchangeRedisCache(opts =>
            {
                opts.Configuration = redisConnectionString;
                opts.InstanceName = redisSettings.InstanceName;
            });
        }
        else
        {
            // Fallback to in-memory cache when Redis is disabled or not configured
            services.AddDistributedMemoryCache();
            
            // Ensure RedisSettings is configured with defaults for CacheService
            if (redisSettings == null)
            {
                services.Configure<RedisSettings>(opts =>
                {
                    opts.Enabled = false;
                    opts.InstanceName = "BlogApp_";
                    opts.DefaultExpirationMinutes = 60;
                });
            }
        }

        // UnitOfWork
        services.AddScoped<IUnitOfWork, UnitOfWork>();
        
        // Entity-Specific Repositories
        services.AddScoped<IBlogPostReadRepository, EfCoreBlogPostReadRepository>();
        services.AddScoped<IBlogPostWriteRepository, EfCoreBlogPostWriteRepository>();
        services.AddScoped<IUserReadRepository, EfCoreUserReadRepository>();
        services.AddScoped<IUserWriteRepository, EfCoreUserWriteRepository>();
        services.AddScoped<ICategoryReadRepository, EfCoreCategoryReadRepository>();
        services.AddScoped<ICategoryWriteRepository, EfCoreCategoryWriteRepository>();
        services.AddScoped<ITagReadRepository, EfCoreTagReadRepository>();
        services.AddScoped<ITagWriteRepository, EfCoreTagWriteRepository>();
        services.AddScoped<ICommentReadRepository, EfCoreCommentReadRepository>();
        services.AddScoped<ICommentWriteRepository, EfCoreCommentWriteRepository>();
        services.AddScoped<IRefreshTokenReadRepository, EfCoreRefreshTokenReadRepository>();
        services.AddScoped<IRefreshTokenWriteRepository, EfCoreRefreshTokenWriteRepository>();
        
        // Generic Repositories (still available for flexibility)
        services.AddScoped(typeof(IRepository<>), typeof(EfCoreRepository<>));
        services.AddScoped(typeof(IReadRepository<>), typeof(EfCoreReadRepository<>));
        services.AddScoped(typeof(IWriteRepository<>), typeof(EfCoreWriteRepository<>));

        // Cache Metrics (using BuildingBlocks with domain-specific meter name)
        services.AddSingleton(sp =>
        {
            var meterFactory = sp.GetService<System.Diagnostics.Metrics.IMeterFactory>();
            return new CacheMetrics(meterFactory, "BlogApp.Cache");
        });

        // Services
        services.AddScoped<IJwtTokenService, JwtTokenService>();

        // Cache Services - ICacheService extends IHybridCacheService extends IBasicCacheService
        // All interfaces resolve to the same CacheService instance
        services.AddScoped<ICacheService, CacheService>();
        services.AddScoped<IHybridCacheService>(sp => sp.GetRequiredService<ICacheService>());
        services.AddScoped<IBasicCacheService>(sp => sp.GetRequiredService<ICacheService>());
        
        services.AddScoped<ICurrentUserService, CurrentUserService>();
        services.AddScoped<IFileStorageService, FileStorageService>();
        services.AddScoped<ITagService, TagService>();

        // Database Seeder
        services.AddScoped<DbSeeder>();

        // Background Services
        services.AddHostedService<RefreshTokenCleanupService>();

        // Messaging Services (RabbitMQ via Shared Library)
        services.AddMessagingServices(configuration);

        return services;
    }
}
