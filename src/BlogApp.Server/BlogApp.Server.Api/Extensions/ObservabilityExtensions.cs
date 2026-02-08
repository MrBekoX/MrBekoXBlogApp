using BlogApp.BuildingBlocks.Caching.Options;
using BlogApp.BuildingBlocks.Messaging.Options;
using OpenTelemetry.Metrics;
using OpenTelemetry.Trace;
using Serilog;

namespace BlogApp.Server.Api.Extensions;

public static class ObservabilityExtensions
{
    public static WebApplicationBuilder AddSerilogLogging(this WebApplicationBuilder builder)
    {
        if (builder.Environment.IsDevelopment())
        {
            builder.Configuration.AddUserSecrets<Program>();
        }

        Log.Logger = new LoggerConfiguration()
            .ReadFrom.Configuration(builder.Configuration)
            .Enrich.FromLogContext()
            .WriteTo.Console()
            .MinimumLevel.Is(builder.Environment.IsDevelopment() ? Serilog.Events.LogEventLevel.Debug : Serilog.Events.LogEventLevel.Warning)
            .WriteTo.File("logs/blogapp-.log", rollingInterval: RollingInterval.Day)
            .CreateLogger();

        builder.Host.UseSerilog();

        return builder;
    }

    public static IServiceCollection AddObservabilityServices(this IServiceCollection services, IConfiguration configuration)
    {
        // OpenTelemetry Metrics for Cache Observability
        services.AddOpenTelemetry()
            .WithMetrics(metrics =>
            {
                metrics
                    .AddMeter("BlogApp.Cache")
                    .AddPrometheusExporter();
            })
            .WithTracing(tracing =>
            {
                tracing
                    .AddAspNetCoreInstrumentation()
                    .AddHttpClientInstrumentation()
                    .AddEntityFrameworkCoreInstrumentation()
                    .AddSource("BlogApp.Messaging");
            });

        // Health checks for PostgreSQL, Redis, and RabbitMQ
        var healthChecks = services.AddHealthChecks();

        var connectionString = configuration.GetConnectionString("DefaultConnection");
        if (!string.IsNullOrEmpty(connectionString))
        {
            healthChecks.AddNpgSql(
                connectionString,
                name: "postgresql",
                tags: new[] { "db", "ready" });
        }

        var redisSettings = configuration.GetSection(RedisSettings.SectionName).Get<RedisSettings>();
        var redisConnectionString = redisSettings?.ConnectionString
                                    ?? configuration.GetConnectionString("Redis");
        if (redisSettings?.Enabled == true && !string.IsNullOrEmpty(redisConnectionString))
        {
            healthChecks.AddRedis(
                redisConnectionString,
                name: "redis",
                tags: new[] { "cache", "ready" });
        }

        var rabbitMqSettings = configuration.GetSection(RabbitMqSettings.SectionName).Get<RabbitMqSettings>();
        if (rabbitMqSettings?.Enabled == true)
        {
            // Note: RabbitMQ healthcheck removed in v9 due to API breaking changes
            // Connection validation is handled by RabbitMqConnection instead
        }

        return services;
    }
}
