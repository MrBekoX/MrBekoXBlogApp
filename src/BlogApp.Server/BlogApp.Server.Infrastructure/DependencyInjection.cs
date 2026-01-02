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
        var connectionString = configuration.GetConnectionString("DefaultConnection");
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

        // Redis Cache
        var redisConnectionString = configuration.GetConnectionString("Redis");
        if (!string.IsNullOrEmpty(redisConnectionString))
        {
            services.AddSingleton<StackExchange.Redis.IConnectionMultiplexer>(sp =>
                StackExchange.Redis.ConnectionMultiplexer.Connect(redisConnectionString));
            
            services.AddStackExchangeRedisCache(options =>
            {
                options.Configuration = redisConnectionString;
                options.InstanceName = "BlogApp_";
            });
        }
        else
        {
            services.AddDistributedMemoryCache();
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

        // Cache Metrics
        services.AddSingleton<CacheMetrics>();

        // Services
        services.AddScoped<IJwtTokenService, JwtTokenService>();
        services.AddScoped<ICacheService, CacheService>();
        services.AddScoped<ICurrentUserService, CurrentUserService>();
        services.AddScoped<IFileStorageService, FileStorageService>();
        services.AddScoped<ITagService, TagService>();

        // Database Seeder
        services.AddScoped<DbSeeder>();

        return services;
    }
}
