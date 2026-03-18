using BlogApp.Server.Api.Extensions;
using BlogApp.Server.Api.Hubs;
using BlogApp.Server.Api.Middlewares;
using BlogApp.Server.Application;
using BlogApp.Server.Application.Common.Security;
using BlogApp.Server.Infrastructure;
using BlogApp.Server.Infrastructure.Persistence;
using Microsoft.AspNetCore.HttpOverrides;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.FileProviders;
using Serilog;

var builder = WebApplication.CreateBuilder(args);

builder.WebHost.ConfigureKestrel(options =>
{
    options.Limits.MaxRequestBodySize = 50_000_000;
});

builder.Services.Configure<Microsoft.AspNetCore.Http.Features.FormOptions>(options =>
{
    options.MultipartBodyLengthLimit = 50_000_000;
    options.ValueLengthLimit = int.MaxValue;
    options.MultipartHeadersLengthLimit = int.MaxValue;
});

builder.AddSerilogLogging();
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

app.UseSwaggerInDevelopment();

var forwardedHeaderOptions = new ForwardedHeadersOptions
{
    ForwardedHeaders = ForwardedHeaders.XForwardedFor | ForwardedHeaders.XForwardedProto,
    ForwardLimit = 1
};
app.UseForwardedHeaders(forwardedHeaderOptions);

app.UseSecurityHeaders();
app.UseExceptionHandling();
app.UseRequestLogging();
app.UseResponseCompression();
app.UseMiddleware<SignalRConnectionLimitMiddleware>();

if (!app.Environment.IsDevelopment())
{
    app.UseHsts();
}

app.UseHttpsRedirection();

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
app.MapHealthChecks("/health");
app.MapHub<PublicCacheHub>("/hubs/public-cache").AllowAnonymous();
app.MapHub<AuthoringEventsHub>("/hubs/authoring-events").RequireAuthorization();
app.MapHub<ChatEventsHub>("/hubs/chat-events").RequireAuthorization(policy =>
{
    policy.AddAuthenticationSchemes(ChatSessionTokenDefaults.SchemeName);
    policy.RequireAuthenticatedUser();
    policy.RequireClaim(ChatSessionTokenDefaults.TokenUseClaim, ChatSessionTokenDefaults.TokenUseValue);
});
app.MapPrometheusScrapingEndpoint("/metrics");

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
