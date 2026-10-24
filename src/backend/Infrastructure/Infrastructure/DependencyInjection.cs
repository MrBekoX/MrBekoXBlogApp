using BlogApp.BuildingBlocks;
using BlogApp.BuildingBlocks.Abstractions;
using BlogApp.BuildingBlocks.Metrics;
using BlogApp.BuildingBlocks.Options;
using BlogApp.Core.Application.Common.AuthorProfile;
using BlogApp.Core.Application.Common.Interfaces.Data;
using BlogApp.Core.Application.Common.Interfaces.Persistence;
using BlogApp.Core.Application.Common.Interfaces.Persistence.BlogPostRepository;
using BlogApp.Core.Application.Common.Interfaces.Persistence.CategoryRepository;
using BlogApp.Core.Application.Common.Interfaces.Persistence.CommentRepository;
using BlogApp.Core.Application.Common.Interfaces.Persistence.RefreshTokenRepository;
using BlogApp.Core.Application.Common.Interfaces.Persistence.TagRepository;
using BlogApp.Core.Application.Common.Interfaces.Persistence.UserRepository;
using BlogApp.Core.Application.Common.Interfaces.Services;
using BlogApp.Core.Application.Common.Options;
using BlogApp.Infrastructure.Persistence;
using BlogApp.Infrastructure.Persistence.Repositories;
using BlogApp.Infrastructure.Persistence.Repositories.EfCoreBlogPostRepository;
using BlogApp.Infrastructure.Persistence.Repositories.EfCoreCategoryRepository;
using BlogApp.Infrastructure.Persistence.Repositories.EfCoreCommentRepository;
using BlogApp.Infrastructure.Persistence.Repositories.EfCoreRefreshTokenRepository;
using BlogApp.Infrastructure.Persistence.Repositories.EfCoreTagRepository;
using BlogApp.Infrastructure.Persistence.Repositories.EfCoreUserRepository;
using BlogApp.Infrastructure.Services;
using BlogApp.Infrastructure.Services.AuthorProfile;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Diagnostics;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;

namespace BlogApp.Infrastructure;

public static class DependencyInjection
{
    public static IServiceCollection AddInfrastructureServices(this IServiceCollection services, IConfiguration configuration)
    {
        services.Configure<JwtSettings>(configuration.GetSection(JwtSettings.SectionName));
        services.AddOptions<AdminUserSettings>()
            .Bind(configuration.GetSection(AdminUserSettings.SectionName))
            .PostConfigure(settings =>
            {
                // Keep legacy flat environment configuration compatible without
                // reading process globals from the database bootstrapper.
                settings.Email = configuration["ADMIN_EMAIL"] ?? settings.Email;
                settings.UserName = configuration["ADMIN_USERNAME"] ?? settings.UserName;
                settings.Password = configuration["ADMIN_PASSWORD"] ?? settings.Password;
            });

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

        // Canonical yazar profili (K2): tek onaylı, sürümlü public kaynak; /api/v1/profile,
        // agent kabulü (snapshot pin) ve sunum denetimi aynı okuyucuyu paylaşır.
        services.Configure<AuthorProfileSettings>(configuration.GetSection(AuthorProfileSettings.SectionName));
        services.AddSingleton<IAuthorProfileSource, FileAuthorProfileSource>();

        services.AddScoped<DbSeeder>();
        services.AddHostedService<RefreshTokenCleanupService>();
        services.AddHostedService<IdempotencyCleanupService>();

        return services;
    }
}


