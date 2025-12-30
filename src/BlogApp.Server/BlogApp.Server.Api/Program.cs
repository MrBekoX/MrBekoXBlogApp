using System.IO.Compression;
using System.Text;
using AspNetCoreRateLimit;
using BlogApp.Server.Api.Extensions;
using BlogApp.Server.Api.Hubs;
using BlogApp.Server.Api.Middlewares;
using BlogApp.Server.Api.Services;
using BlogApp.Server.Application;
using BlogApp.Server.Application.Common.Interfaces;
using BlogApp.Server.Application.Common.Options;
using BlogApp.Server.Infrastructure;
using BlogApp.Server.Infrastructure.Services;
using Microsoft.AspNetCore.Authentication.JwtBearer;
using Microsoft.AspNetCore.ResponseCompression;
using Microsoft.IdentityModel.Tokens;
using Serilog;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.FileProviders;
using Microsoft.AspNetCore.HttpOverrides;
using OpenTelemetry.Metrics;
using Asp.Versioning;

var builder = WebApplication.CreateBuilder(args);

if (builder.Environment.IsDevelopment())
{
    builder.Configuration.AddUserSecrets<Program>();
}

Log.Logger = new LoggerConfiguration()
    .ReadFrom.Configuration(builder.Configuration)
    .Enrich.FromLogContext()
    .WriteTo.Console()
    .MinimumLevel.Debug() // Debug seviyesini aç
    .WriteTo.File("logs/blogapp-.log", rollingInterval: RollingInterval.Day)
    .CreateLogger();

builder.Host.UseSerilog();

// Minimal API JSON configuration
builder.Services.ConfigureHttpJsonOptions(options =>
{
    options.SerializerOptions.Converters.Add(new System.Text.Json.Serialization.JsonStringEnumConverter());
});

// API Versioning
builder.Services.AddApiVersioning(options =>
{
    options.DefaultApiVersion = new ApiVersion(1, 0);
    options.AssumeDefaultVersionWhenUnspecified = true;
    options.ReportApiVersions = true;
    options.ApiVersionReader = new UrlSegmentApiVersionReader();
});

builder.Services.AddEndpointsApiExplorer();
builder.Services.AddSwaggerGen();
builder.Services.AddOutputCache(options =>
{
    // Default policy: 60 seconds
    options.AddBasePolicy(policy => policy.Expire(TimeSpan.FromSeconds(60)));

    // Short cache for lists (affected by new posts)
    options.AddPolicy("PostsList", policy =>
        policy.Expire(TimeSpan.FromMinutes(1))
              .Tag("posts"));

    // Medium cache for individual posts
    options.AddPolicy("PostDetail", policy =>
        policy.Expire(TimeSpan.FromMinutes(5))
              .SetVaryByRouteValue("slug", "id")
              .Tag("posts"));

    // Longer cache for static-ish content
    options.AddPolicy("Categories", policy =>
        policy.Expire(TimeSpan.FromMinutes(10))
              .Tag("categories"));

    options.AddPolicy("Tags", policy =>
        policy.Expire(TimeSpan.FromMinutes(10))
              .Tag("tags"));
});

// CSRF/Antiforgery configuration for SPA
builder.Services.AddAntiforgery(options =>
{
    options.HeaderName = "X-CSRF-TOKEN";
    options.Cookie.Name = "BlogApp.CSRF";
    options.Cookie.HttpOnly = true;
    options.Cookie.SecurePolicy = CookieSecurePolicy.SameAsRequest;
    options.Cookie.SameSite = SameSiteMode.Strict;
});

// JWT Settings via Options Pattern
var jwtSettings = builder.Configuration.GetSection(JwtSettings.SectionName).Get<JwtSettings>()
    ?? throw new InvalidOperationException("JWT settings not configured");

builder.Services.AddAuthentication(options =>
{
    options.DefaultAuthenticateScheme = JwtBearerDefaults.AuthenticationScheme;
    options.DefaultChallengeScheme = JwtBearerDefaults.AuthenticationScheme;
})
.AddJwtBearer(options =>
{
    options.TokenValidationParameters = new TokenValidationParameters
    {
        ValidateIssuerSigningKey = true,
        IssuerSigningKey = new SymmetricSecurityKey(Encoding.UTF8.GetBytes(jwtSettings.Secret)),
        ValidateIssuer = true,
        ValidIssuer = jwtSettings.Issuer,
        ValidateAudience = true,
        ValidAudience = jwtSettings.Audience,
        ValidateLifetime = true,
        ClockSkew = TimeSpan.Zero
    };
    options.Events = new JwtBearerEvents
    {
        OnMessageReceived = context =>
        {
            if (string.IsNullOrEmpty(context.Token))
            {
                context.Token = context.Request.Cookies["BlogApp.AccessToken"];
            }
            return Task.CompletedTask;
        }
    };
});

builder.Services.AddAuthorization();

// CORS Settings - Hardened configuration
var corsOrigins = builder.Configuration.GetSection("CorsOrigins").Get<string[]>() ?? ["http://localhost:3000"];
builder.Services.AddCors(options =>
{
    options.AddPolicy("AllowFrontend", policy =>
    {
        policy.WithOrigins(corsOrigins)
            .WithMethods("GET", "POST", "PUT", "DELETE", "OPTIONS")
            .WithHeaders("Content-Type", "Authorization", "X-Requested-With", "Accept", "X-SignalR-User-Agent", "X-CSRF-TOKEN")
            .WithExposedHeaders("Content-Disposition")
            .AllowCredentials()
            .SetPreflightMaxAge(TimeSpan.FromMinutes(10));
    });
});

// Response Compression for better performance
builder.Services.AddResponseCompression(options =>
{
    options.EnableForHttps = true;
    options.Providers.Add<BrotliCompressionProvider>();
    options.Providers.Add<GzipCompressionProvider>();
    options.MimeTypes = ResponseCompressionDefaults.MimeTypes.Concat(["application/json", "text/plain", "text/html", "application/xml", "text/xml"]);
});
builder.Services.Configure<BrotliCompressionProviderOptions>(options => options.Level = CompressionLevel.Fastest);
builder.Services.Configure<GzipCompressionProviderOptions>(options => options.Level = CompressionLevel.SmallestSize);

// L1 Cache (in-memory) configuration
// Note: SizeLimit removed because AspNetCoreRateLimit doesn't set Size on cache entries
// Our CacheService manages L1 cache limits via internal key tracking
builder.Services.AddMemoryCache();
builder.Services.Configure<IpRateLimitOptions>(builder.Configuration.GetSection("IpRateLimiting"));
builder.Services.AddInMemoryRateLimiting();
builder.Services.AddSingleton<IRateLimitConfiguration, RateLimitConfiguration>();
builder.Services.AddHttpContextAccessor();
builder.Services.AddApplicationServices();
builder.Services.AddInfrastructureServices(builder.Configuration);

// SignalR for real-time cache invalidation notifications
builder.Services.AddSignalR();
builder.Services.AddScoped<ICacheInvalidationNotifier, CacheInvalidationNotifier>();

// OpenTelemetry Metrics for Cache Observability
builder.Services.AddOpenTelemetry()
    .WithMetrics(metrics =>
    {
        metrics
            .AddMeter(CacheMetrics.MeterName)
            .AddPrometheusExporter();
    });

builder.Services.AddHealthChecks();

var app = builder.Build();

if (app.Environment.IsDevelopment())
{
    app.UseSwagger();
    app.UseSwaggerUI(options =>
    {
        options.SwaggerEndpoint("/swagger/v1/swagger.json", "BlogApp API v1");
        options.RoutePrefix = "swagger";
    });
}

// Proxy arkasında çalışırken X-Forwarded-* header'larını işle
// Proxy arkasında çalışırken X-Forwarded-* header'larını işle
var forwardedHeaderOptions = new ForwardedHeadersOptions
{
    ForwardedHeaders = ForwardedHeaders.XForwardedFor | ForwardedHeaders.XForwardedProto
};
// Docker/ALB ağındaki dinamik IP'lere güvenmek için listeleri temizliyoruz
forwardedHeaderOptions.KnownNetworks.Clear();
forwardedHeaderOptions.KnownProxies.Clear();

app.UseForwardedHeaders(forwardedHeaderOptions);

// Security Headers - must be early in pipeline
app.UseSecurityHeaders();

app.UseExceptionHandling();
app.UseRequestLogging();

// Response compression
app.UseResponseCompression();

// HTTPS redirect in production (Development uses HTTP for easier debugging)
// Bu kısmı sadece Development için çalışacak hale getir
if (app.Environment.IsDevelopment())
{
    app.UseHttpsRedirection();
}
else 
{
    // Production'da HSTS kullanabilirsin ama HTTPS yönlendirmesini Nginx yapmalı
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
    // API yanıtlarını tarayıcının önbelleklemesini engelle
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

// Register Minimal API Endpoints
app.RegisterAllEndpoints();
app.MapHealthChecks("/health");

// SignalR Hub for real-time cache invalidation notifications
app.MapHub<CacheInvalidationHub>("/hubs/cache");

// Prometheus metrics endpoint for cache observability
app.MapPrometheusScrapingEndpoint("/metrics");

using (var scope = app.Services.CreateScope())
{
    var context = scope.ServiceProvider.GetRequiredService<BlogApp.Server.Infrastructure.Persistence.AppDbContext>();
    if (app.Environment.IsProduction())
    {
        Log.Information("Applying migrations...");
        await context.Database.MigrateAsync();
    }
    else
    {
        await context.Database.EnsureCreatedAsync();
    }
    var seeder = scope.ServiceProvider.GetRequiredService<BlogApp.Server.Infrastructure.Persistence.DbSeeder>();
    await seeder.SeedAsync();
}

Log.Information("BlogApp API starting...");
try { await app.RunAsync(); }
catch (Exception ex) { Log.Fatal(ex, "Application terminated unexpectedly"); }
finally { Log.CloseAndFlush(); }
