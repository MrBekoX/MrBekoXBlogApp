using BlogApp.Server.Api.Extensions;
using BlogApp.Server.Api.Hubs;
using BlogApp.Server.Api.Middlewares;
using BlogApp.Server.Application;
using BlogApp.Server.Application.Common.Options;
using BlogApp.Server.Infrastructure;
using BlogApp.Server.Infrastructure.Persistence;
using Microsoft.AspNetCore.DataProtection;
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
builder.Services.AddSignalR(options =>
{
    options.KeepAliveInterval = TimeSpan.FromSeconds(serverLimits.SignalRKeepAliveIntervalSeconds);
    options.ClientTimeoutInterval = TimeSpan.FromSeconds(serverLimits.SignalRClientTimeoutSeconds);
    options.HandshakeTimeout = TimeSpan.FromSeconds(serverLimits.SignalRHandshakeTimeoutSeconds);
});
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

var internalHosts = builder.Configuration.GetSection("InternalHosts").Get<string[]>() ?? ["localhost", "127.0.0.1"];
app.MapHealthChecks("/health").RequireHost(internalHosts);
app.MapHub<PublicCacheHub>("/hubs/public-cache").AllowAnonymous();
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
