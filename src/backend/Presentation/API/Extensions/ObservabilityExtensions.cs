using System.Diagnostics;
using System.Globalization;
using BlogApp.BuildingBlocks.Options;
using BlogApp.Presentation.Api.Health;
using BlogApp.Infrastructure.Messaging;
using BlogApp.Presentation.Api.Services;
using OpenTelemetry;
using OpenTelemetry.Exporter;
using OpenTelemetry.Resources;
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
            .ConfigureResource(resource => resource.AddService("blogapp-api"))
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
                    .AddAspNetCoreInstrumentation(options =>
                    {
                        options.RecordException = false;
                    })
                    .AddHttpClientInstrumentation(options =>
                    {
                        options.RecordException = false;
                    })
                    .AddEntityFrameworkCoreInstrumentation(options =>
                        options.EnrichWithIDbCommand = (activity, _) =>
                        {
                            activity.SetTag("db.query.text", null);
                            activity.SetTag("db.statement", null);
                        })
                    .AddSource("BlogApp");

                // Explicit opt-in only. Do not enable OTLP logging or payload capture.
                var configuredEndpoint = configuration["AgentTelemetry:Endpoint"]?.Trim();
                if (!string.IsNullOrEmpty(configuredEndpoint))
                {
                    if (!Uri.TryCreate(configuredEndpoint, UriKind.Absolute, out var endpoint)
                        || endpoint.Scheme is not ("http" or "https")
                        || string.IsNullOrEmpty(endpoint.Host)
                        || !endpoint.AbsolutePath.EndsWith("/v1/traces", StringComparison.Ordinal)
                        || !string.IsNullOrEmpty(endpoint.UserInfo)
                        || !string.IsNullOrEmpty(endpoint.Query)
                        || !string.IsNullOrEmpty(endpoint.Fragment))
                        throw new ArgumentException("AgentTelemetry:Endpoint must be an absolute HTTP(S) traces URL ending in /v1/traces without credentials, query or fragment.");
                    var timeout = 1000;
                    var configuredTimeout = configuration["AgentTelemetry:TimeoutMilliseconds"];
                    if (configuredTimeout is not null
                        && !int.TryParse(configuredTimeout, NumberStyles.Integer, CultureInfo.InvariantCulture, out timeout)
                        || timeout is < 100 or > 10000)
                        throw new ArgumentException("AgentTelemetry:TimeoutMilliseconds must be an integer between 100 and 10000.");
                    tracing.AddProcessor(new AgentTelemetryPrivacyProcessor())
                        .AddOtlpExporter(options =>
                        {
                            options.Endpoint = endpoint;
                            options.Protocol = OtlpExportProtocol.HttpProtobuf;
                            options.TimeoutMilliseconds = timeout;
                            options.BatchExportProcessorOptions = new BatchExportProcessorOptions<Activity>
                            {
                                MaxQueueSize = 512,
                                MaxExportBatchSize = 128,
                                ScheduledDelayMilliseconds = 1000,
                                ExporterTimeoutMilliseconds = timeout,
                            };
                        });
                }
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
