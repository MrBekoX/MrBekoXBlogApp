using BlogApp.Presentation.Api.Services;
using BlogApp.Presentation.Api.Endpoints;
using BlogApp.Presentation.Api.Extensions;
using BlogApp.Presentation.Api.Health;
using BlogApp.Presentation.Api.Hubs;
using BlogApp.Presentation.Api.Middlewares;
using BlogApp.BuildingBlocks.Messaging;
using BlogApp.Core.Application;
using BlogApp.Core.Application.Common.Interfaces.Data;
using BlogApp.Core.Application.Common.Messaging;
using BlogApp.Core.Application.Common.Options;
using BlogApp.Core.Application.Features.AgentFeature.Commands.RecordAgentFeedbackCommand;
using BlogApp.Core.Application.Features.AgentFeature.Commands.ResumeAgentRunCommand;
using BlogApp.Core.Application.Features.AgentFeature.Queries.GetAgentObservationsQuery;
using BlogApp.Infrastructure;
using BlogApp.Infrastructure.Messaging;
using BlogApp.Infrastructure.Persistence;
using Microsoft.AspNetCore.DataProtection;
using Microsoft.AspNetCore.Diagnostics.HealthChecks;
using Microsoft.AspNetCore.HttpOverrides;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.FileProviders;
using Serilog;

var builder = WebApplication.CreateBuilder(args);

// Bind ServerLimits configuration
var serverLimits = builder.Configuration
    .GetSection(ServerLimitsSettings.SectionName)
    .Get<ServerLimitsSettings>() ?? new ServerLimitsSettings();
builder.Services.Configure<ServerLimitsSettings>(
    builder.Configuration.GetSection(ServerLimitsSettings.SectionName));

builder.WebHost.ConfigureKestrel(options =>
{
    options.Limits.MaxRequestBodySize = serverLimits.MaxRequestBodySizeBytes;
});

builder.Services.Configure<Microsoft.AspNetCore.Http.Features.FormOptions>(options =>
{
    options.MultipartBodyLengthLimit = serverLimits.MultipartBodyLengthLimit;
    options.ValueLengthLimit = serverLimits.FormValueLengthLimit;
    options.MultipartHeadersLengthLimit = serverLimits.MultipartHeadersLengthLimit;
});

builder.AddSerilogLogging();
builder.Services.AddSwaggerServices();
builder.Services.AddOutputCachePolicies(builder.Configuration);
builder.Services.AddResponseCompressionServices();
builder.Services.AddSecurityServices(builder.Configuration, builder.Environment);
builder.Services.AddJwtAuthentication(builder.Configuration);
builder.Services.AddCorsPolicy(builder.Configuration, builder.Environment);
builder.Services.AddHttpContextAccessor();
builder.Services.AddApplicationServices();
builder.Services.AddInfrastructureServices(builder.Configuration);

// ---- B10 agent mesajlaşma ve gözlem hattı kablolaması (B3/B5/B8 servisleri bu faza bağlandı) ----
// B2 broker temeli: bağlantı yöneticisi + topoloji declarer (K3: bildirim aşağıdaki
// hosted servis ile başlangıçta çağrılır; broker kapalıysa uygulama fail-fast OLMADAN
// kalkmaya devam eder — kabul yolu DB outbox'ıdır, yayın relay'inin kendi döngüsü vardır).
builder.Services.AddRabbitMqAgentMessaging(builder.Configuration);
builder.Services.AddAgentOutbox(builder.Configuration);          // B3: outbox yazıcı + relay
builder.Services.AddAgentEventProjection(builder.Configuration); // B5: olay inbox + projection + hub bildirimi
builder.Services.AddAgentContentEvents(builder.Configuration);   // B8: içerik olayları + sunum denetimi (F2 notu)
builder.Services.AddAgentCollaboration(builder.Configuration);   // B9: proposal store + iş birliği servisi (projection handler'ın store bağımlılığı)
builder.Services.AddHostedService<AgentTopologyInitializerHost>();

// B10 endpoint destek servisleri: misafir oturumu, B9-resume durumu, geri bildirim kaydı,
// agent şeması gözlem bağlantısı.
builder.Services.AddScoped<IAgentGuestSessionService, AgentGuestSessionService>();
builder.Services.AddScoped<IAgentResumeStateStore, ProjectionAgentResumeStateStore>();
builder.Services.AddScoped<IAgentFeedbackStore, ProjectionAgentFeedbackStore>();
builder.Services.AddSingleton<IAgentSystemDbConnectionFactory, AgentSystemDbConnectionFactory>();

builder.Services.AddSignalR(options =>
{
    options.KeepAliveInterval = TimeSpan.FromSeconds(serverLimits.SignalRKeepAliveIntervalSeconds);
    options.ClientTimeoutInterval = TimeSpan.FromSeconds(serverLimits.SignalRClientTimeoutSeconds);
    options.HandshakeTimeout = TimeSpan.FromSeconds(serverLimits.SignalRHandshakeTimeoutSeconds);
});
// B5: projection commit'i sonrası agent run canlı bildirim yayını (ince katman).
builder.Services.AddSingleton<IAgentRunNotifier, SignalRAgentRunNotifier>();
builder.Services.AddObservabilityServices(builder.Configuration);

// DataProtection — persist keys so cookies survive container restarts
var keysPath = Path.Combine(builder.Environment.ContentRootPath, "keys");
if (!Directory.Exists(keysPath)) Directory.CreateDirectory(keysPath);
builder.Services.AddDataProtection()
    .PersistKeysToFileSystem(new DirectoryInfo(keysPath))
    .SetApplicationName("BlogApp");

var app = builder.Build();

app.UseSwaggerInDevelopment();

var forwardedHeaderOptions = new ForwardedHeadersOptions
{
    ForwardedHeaders = ForwardedHeaders.XForwardedFor | ForwardedHeaders.XForwardedProto,
    ForwardLimit = serverLimits.ForwardedHeadersForwardLimit
};
// Trust Docker network proxies — ForwardLimit=2 covers ALB + nginx
forwardedHeaderOptions.KnownIPNetworks.Clear();
forwardedHeaderOptions.KnownProxies.Clear();
app.UseForwardedHeaders(forwardedHeaderOptions);

app.UseSecurityHeaders();
app.UseExceptionHandling();
app.UseRequestLogging();
app.UseResponseCompression();
app.UseMiddleware<SignalRConnectionLimitMiddleware>();

if (!app.Environment.IsDevelopment())
{
    // HSTS header — nginx de set eder ama defense-in-depth
    app.UseHsts();
}
// UseHttpsRedirection kaldirildi — ALB/nginx SSL termination yapiyor,
// backend'de HTTPS port yok. Redirect infrastructure katmaninda hallediliyor.

var uploadsPath = Path.Combine(app.Environment.ContentRootPath, "uploads");
if (!Directory.Exists(uploadsPath)) Directory.CreateDirectory(uploadsPath);

app.UseStaticFiles(new StaticFileOptions
{
    FileProvider = new PhysicalFileProvider(uploadsPath),
    RequestPath = "/uploads"
});

app.UseCors("AllowFrontend");
app.UseIpRateLimiting();
app.UseAuthentication();
app.UseAuthorization();
app.UseOutputCache();
app.UseAntiforgery();

app.RegisterAllEndpoints();
app.RegisterAgentEndpoints();

var internalHosts = builder.Configuration.GetSection("InternalHosts").Get<string[]>() ?? ["localhost", "127.0.0.1"];
app.MapHealthChecks("/health").RequireHost(internalHosts);
// B11 sağlık ayrımı (plan satır 561): liveness, hazır-bulunurluk ve agent hattı
// kontrolleri AYRI uç noktalardadır. Docker/orkestratör container liveness'ı için
// /health/live kullanılır (bağımlılık yok; broker/DB kapalıyken container
// restart edilmez — K3). /health/ready db+redis'i denetler (trafiğe hazır).
// /health/agent broker bağlantısı + outbox backlog'u raporlar (operatör sinyali;
// Degraded/Unhealthy'de kabul yolu çalışmaya DEVAM EDER, işler beklemde gösterilir).
app.MapHealthChecks("/health/live", new HealthCheckOptions
{
    Predicate = _ => false, // liveness: yalnız sürecin yanıt verdiği
}).RequireHost(internalHosts);
app.MapHealthChecks("/health/ready", new HealthCheckOptions
{
    Predicate = check => check.Tags.Contains("ready"),
}).RequireHost(internalHosts);
app.MapHealthChecks("/health/agent", new HealthCheckOptions
{
    Predicate = check => check.Tags.Contains("agent"),
    ResponseWriter = AgentHealthResponseWriter.WriteAsync, // JSON gövde: backlog sayıları taşınır
}).RequireHost(internalHosts);
app.MapHub<PublicCacheHub>("/hubs/public-cache").AllowAnonymous();
// B5: agent run canlı bildirim hub'ı (replay GET uç noktaları B10'da).
app.MapHub<AgentRunsHub>(AgentRunsHub.HubPath).AllowAnonymous();
app.MapPrometheusScrapingEndpoint("/metrics").RequireHost(internalHosts);

// Run migrations and seeding based on configuration
// Production: automatic (no EF Core CLI needed in container)
// Development: manual (developer controls when to run)
var runMigrations = builder.Configuration.GetValue<bool>("Database:RunMigrationsOnStartup", !app.Environment.IsDevelopment());

if (runMigrations)
{
    using (var scope = app.Services.CreateScope())
    {
        var context = scope.ServiceProvider.GetRequiredService<AppDbContext>();
        Log.Information("Applying migrations...");
        await context.Database.MigrateAsync();
    }
}
else
{
    Log.Information("Skipping automatic migrations. Run them manually via: dotnet ef database update");
}

// Always seed in Development - even if migrations are manual
if (app.Environment.IsDevelopment())
{
    using (var scope = app.Services.CreateScope())
    {
        var seeder = scope.ServiceProvider.GetRequiredService<DbSeeder>();
        await seeder.SeedAsync();
    }
}

Log.Information("BlogApp API starting...");
try { await app.RunAsync(); }
catch (Exception ex) { Log.Fatal(ex, "Application terminated unexpectedly"); }
finally { Log.CloseAndFlush(); }
