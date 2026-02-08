using BlogApp.Server.Api.Extensions;
using BlogApp.Server.Api.Hubs;
using BlogApp.Server.Api.Middlewares;
using BlogApp.Server.Application;
using BlogApp.Server.Infrastructure;
using BlogApp.Server.Infrastructure.Persistence;
using Microsoft.AspNetCore.HttpOverrides;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.FileProviders;
using Serilog;

var builder = WebApplication.CreateBuilder(args);

// ==================== Logging ====================
builder.AddSerilogLogging();

// ==================== Services ====================
builder.Services.AddSwaggerServices();
builder.Services.AddOutputCachePolicies();
builder.Services.AddResponseCompressionServices();
builder.Services.AddSecurityServices(builder.Configuration);
builder.Services.AddJwtAuthentication(builder.Configuration);
builder.Services.AddCorsPolicy(builder.Configuration, builder.Environment);
builder.Services.AddHttpContextAccessor();
builder.Services.AddApplicationServices();
builder.Services.AddInfrastructureServices(builder.Configuration);
builder.Services.AddMessagingAndSignalR(builder.Configuration);
builder.Services.AddObservabilityServices(builder.Configuration);

var app = builder.Build();

// ==================== Middleware Pipeline ====================
app.UseSwaggerInDevelopment();

// SECURITY: Process X-Forwarded-* headers from proxy (ALB)
var forwardedHeaderOptions = new ForwardedHeadersOptions
{
    ForwardedHeaders = ForwardedHeaders.XForwardedFor | ForwardedHeaders.XForwardedProto,
    ForwardLimit = 1
    // BUG-022: Removed .Clear() calls to prevent spoofing
    // Default behavior trusts Docker network and known proxies
    // Only clear if you have a specific trusted proxy IP configuration
};
app.UseForwardedHeaders(forwardedHeaderOptions);

app.UseSecurityHeaders();
app.UseExceptionHandling();
app.UseRequestLogging();
app.UseResponseCompression();

if (app.Environment.IsDevelopment())
{
    app.UseHttpsRedirection();
}
else
{
    app.UseHsts();
}

var uploadsPath = Path.Combine(app.Environment.ContentRootPath, "uploads");
if (!Directory.Exists(uploadsPath)) Directory.CreateDirectory(uploadsPath);

app.UseStaticFiles(new StaticFileOptions
{
    FileProvider = new PhysicalFileProvider(uploadsPath),
    RequestPath = "/uploads"
});

app.UseCors("AllowFrontend");

app.Use(async (context, next) =>
{
    context.Response.Headers.Append("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0");
    context.Response.Headers.Append("Pragma", "no-cache");
    context.Response.Headers.Append("Expires", "0");
    await next();
});

app.UseIpRateLimiting();
app.UseAuthentication();
app.UseAuthorization();
app.UseOutputCache();
app.UseAntiforgery();

// ==================== Endpoints ====================
app.RegisterAllEndpoints();
app.MapHealthChecks("/health");
app.MapHub<CacheInvalidationHub>("/hubs/cache");
app.MapPrometheusScrapingEndpoint("/metrics");

// ==================== Database ====================
using (var scope = app.Services.CreateScope())
{
    var context = scope.ServiceProvider.GetRequiredService<AppDbContext>();
    if (app.Environment.IsProduction())
    {
        Log.Information("Applying migrations...");
        await context.Database.MigrateAsync();
    }
    else
    {
        await context.Database.EnsureCreatedAsync();
    }
    var seeder = scope.ServiceProvider.GetRequiredService<DbSeeder>();
    await seeder.SeedAsync();
}

// ==================== Run ====================
Log.Information("BlogApp API starting...");
try { await app.RunAsync(); }
catch (Exception ex) { Log.Fatal(ex, "Application terminated unexpectedly"); }
finally { Log.CloseAndFlush(); }

