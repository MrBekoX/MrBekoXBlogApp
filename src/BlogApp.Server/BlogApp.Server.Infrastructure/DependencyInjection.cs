using BlogApp.Server.Application.Common.Interfaces;
using BlogApp.Server.Infrastructure.Persistence;
using BlogApp.Server.Infrastructure.Persistence.Repositories;
using BlogApp.Server.Infrastructure.Services;
using Microsoft.EntityFrameworkCore;
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
        // Database
        var connectionString = configuration.GetConnectionString("DefaultConnection");
        services.AddDbContext<AppDbContext>(options =>
        {
            options.UseNpgsql(connectionString, npgsqlOptions =>
            {
                npgsqlOptions.MigrationsAssembly(typeof(AppDbContext).Assembly.FullName);
                npgsqlOptions.EnableRetryOnFailure(3);
            });
        });

        services.AddScoped<IApplicationDbContext>(provider =>
            provider.GetRequiredService<AppDbContext>());

        // Redis Cache
        var redisConnectionString = configuration.GetConnectionString("Redis");
        if (!string.IsNullOrEmpty(redisConnectionString))
        {
            services.AddStackExchangeRedisCache(options =>
            {
                options.Configuration = redisConnectionString;
                options.InstanceName = "BlogApp_";
            });
        }
        else
        {
            // Fallback to in-memory cache for development
            services.AddDistributedMemoryCache();
        }

        // Repositories
        services.AddScoped<IUnitOfWork, UnitOfWork>();
        services.AddScoped(typeof(IRepository<>), typeof(EfCoreRepository<>));
        services.AddScoped(typeof(IReadRepository<>), typeof(EfCoreReadRepository<>));
        services.AddScoped(typeof(IWriteRepository<>), typeof(EfCoreWriteRepository<>));

        // Services
        services.AddScoped<IJwtTokenService, JwtTokenService>();
        services.AddScoped<ICacheService, CacheService>();
        services.AddScoped<ICurrentUserService, CurrentUserService>();
        services.AddScoped<IFileStorageService, FileStorageService>();

        // Database Seeder
        services.AddScoped<DbSeeder>();

        return services;
    }
}
