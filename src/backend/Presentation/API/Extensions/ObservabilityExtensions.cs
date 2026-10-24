using BlogApp.BuildingBlocks.Options;
using BlogApp.Presentation.Api.Health;
using BlogApp.Infrastructure.Messaging;
using OpenTelemetry.Metrics;
using OpenTelemetry.Trace;
using Serilog;

namespace BlogApp.Presentation.Api.Extensions;

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
                    .AddMeter(OutboxMetrics.MeterName)
                    .AddPrometheusExporter();
            })
            .WithTracing(tracing =>
            {
                tracing
                    .AddAspNetCoreInstrumentation()
                    .AddHttpClientInstrumentation()
                    .AddEntityFrameworkCoreInstrumentation()
                    .AddSource("BlogApp");
            });

        // Health checks for PostgreSQL and Redis
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

        // B11 agent sağlık ayrımı (plan satır 561): broker readiness ve outbox backlog
        // kontrolleri "ready" tag'ine BAĞLANMAZ — yalnız /health/agent (tag "agent")
        // altında raporlanır; broker kapalıyken uygulama ayakta kalır ve kabul yolu
        // DB outbox'ıyla çalışır (K3). Bu yüzden iki kontrol broker/agent servislerinin
        // kayıtlı olmasına koşullu DEĞİLDİR: yoksa da Degraded/Unhealthy raporlar.
        services.Configure<AgentHealthOptions>(configuration.GetSection(AgentHealthOptions.SectionName));
        healthChecks.AddCheck<AgentBrokerHealthCheck>(
            "agent-broker",
            tags: new[] { "agent", "broker" });
        healthChecks.AddCheck<AgentOutboxBacklogHealthCheck>(
            "agent-outbox-backlog",
            tags: new[] { "agent", "outbox" });

        return services;
    }
}
