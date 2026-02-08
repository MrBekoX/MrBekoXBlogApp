using AspNetCoreRateLimit;
using Microsoft.AspNetCore.Builder;

namespace BlogApp.Server.Api.Extensions;

public static class SecurityExtensions
{
    public static IServiceCollection AddSecurityServices(this IServiceCollection services, IConfiguration configuration)
    {
        // CSRF/Antiforgery configuration for SPA
        services.AddAntiforgery(options =>
        {
            options.HeaderName = "X-CSRF-TOKEN";
            options.Cookie.Name = "BlogApp.CSRF";
            options.Cookie.HttpOnly = true;
            options.Cookie.SecurePolicy = CookieSecurePolicy.SameAsRequest;
            options.Cookie.SameSite = SameSiteMode.Strict;
        });

        // L1 Cache (in-memory) configuration
        // Note: SizeLimit removed because AspNetCoreRateLimit doesn't set Size on cache entries
        // Our CacheService manages L1 cache limits via internal key tracking
        services.AddMemoryCache();
        services.Configure<IpRateLimitOptions>(configuration.GetSection("IpRateLimiting"));
        services.AddInMemoryRateLimiting();
        services.AddSingleton<IRateLimitConfiguration, RateLimitConfiguration>();

        return services;
    }

    public static IApplicationBuilder UseIpRateLimiting(this IApplicationBuilder app)
    {
        return app.UseMiddleware<IpRateLimitMiddleware>();
    }
}
