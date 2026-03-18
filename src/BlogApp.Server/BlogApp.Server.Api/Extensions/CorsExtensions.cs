namespace BlogApp.Server.Api.Extensions;

public static class CorsExtensions
{
    public static IServiceCollection AddCorsPolicy(this IServiceCollection services, IConfiguration configuration, IWebHostEnvironment environment)
    {
        var corsOrigins = configuration.GetSection("CorsOrigins").Get<string[]>();

        // SECURITY: Require explicit CORS configuration in production
        if (environment.IsProduction() && (corsOrigins == null || corsOrigins.Length == 0))
        {
            throw new InvalidOperationException("CorsOrigins must be configured in production environment via environment variables");
        }

        // Development fallback
        corsOrigins ??= ["http://localhost:3000", "https://localhost:3000"];
        services.AddCors(options =>
        {
            options.AddPolicy("AllowFrontend", policy =>
            {
                policy.WithOrigins(corsOrigins)
                    .WithMethods("GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS")
                    .WithHeaders("Content-Type", "Authorization", "X-Requested-With", "Accept", "X-SignalR-User-Agent", "X-CSRF-TOKEN", "Idempotency-Key")
                    .WithExposedHeaders("Content-Disposition", "X-CSRF-TOKEN")
                    .AllowCredentials()
                    .SetPreflightMaxAge(TimeSpan.FromMinutes(10));
            });
        });

        return services;
    }
}

