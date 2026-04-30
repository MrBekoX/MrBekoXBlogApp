using BlogApp.BuildingBlocks.Caching;
using BlogApp.BuildingBlocks.Caching.Abstractions;
using BlogApp.BuildingBlocks.Caching.Metrics;
using BlogApp.BuildingBlocks.Caching.Options;
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
using Microsoft.Extensions.Hosting;

namespace BlogApp.Server.Infrastructure;

public static class DependencyInjection
{
    public static IServiceCollection AddInfrastructureServices(this IServiceCollection services, IConfiguration configuration)
    {
        services.Configure<JwtSettings>(configuration.GetSection(JwtSettings.SectionName));
        services.Configure<AdminUserSettings>(configuration.GetSection(AdminUserSettings.SectionName));

        services.Configure<SiteSettings>(options =>
        {
            var origins = configuration.GetSection("CorsOrigins").Get<string[]>();
            options.Origins = origins ?? ["http://localhost:3000"];
        });

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

            options.ConfigureWarnings(warnings =>
                warnings.Ignore(RelationalEventId.PendingModelChangesWarning));
        });

        services.AddScoped<IApplicationDbContext>(provider =>
            provider.GetRequiredService<AppDbContext>());

        services.AddHybridCachingInfrastructure(
            configuration,
            meterName: "BlogApp.Cache");

        services.AddScoped<IUnitOfWork, UnitOfWork>();

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

        services.AddScoped(typeof(IRepository<>), typeof(EfCoreRepository<>));
        services.AddScoped(typeof(IReadRepository<>), typeof(EfCoreReadRepository<>));
        services.AddScoped(typeof(IWriteRepository<>), typeof(EfCoreWriteRepository<>));

        services.AddScoped<ICacheService, CacheService>();
        services.AddScoped<IHybridCacheService>(sp => sp.GetRequiredService<ICacheService>());
        services.AddScoped<IBasicCacheService>(sp => sp.GetRequiredService<ICacheService>());

        services.AddScoped<ICurrentUserService, CurrentUserService>();
        services.AddScoped<IPostAuthorizationService, PostAuthorizationService>();
        services.AddScoped<IFileStorageService, FileStorageService>();
        services.AddSingleton<IHtmlSanitizerService, HtmlSanitizerService>();

        services.AddScoped<IJwtTokenService, JwtTokenService>();
        services.AddScoped<ITokenBlacklistService, TokenBlacklistService>();
        services.AddScoped<ITagService, TagService>();

        services.AddScoped<IIdempotencyService, IdempotencyService>();

        services.AddScoped<DbSeeder>();
        services.AddHostedService<RefreshTokenCleanupService>();
        services.AddHostedService<IdempotencyCleanupService>();

        return services;
    }
}


