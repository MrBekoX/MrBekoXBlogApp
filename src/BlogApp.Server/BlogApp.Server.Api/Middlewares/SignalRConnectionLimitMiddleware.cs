using System.Collections.Concurrent;
using System.Diagnostics;
using System.Net;
using System.Timers;
using Microsoft.AspNetCore.Http;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;

namespace BlogApp.Server.Api.Middlewares;

/// <summary>
/// Middleware to limit concurrent SignalR connections per IP address
/// </summary>
public class SignalRConnectionLimitMiddleware
{
    private readonly RequestDelegate _next;
    private readonly ILogger<SignalRConnectionLimitMiddleware> _logger;
    private readonly IOptions<SignalRRateLimitOptions> _options;

    // Track connections per IP
    private static readonly ConcurrentDictionary<string, int> _connectionsPerIp = new();
    private static readonly System.Timers.Timer _cleanupTimer;

    static SignalRConnectionLimitMiddleware()
    {
        // Start cleanup timer to remove stale entries (every 5 minutes)
        _cleanupTimer = new System.Timers.Timer(TimeSpan.FromMinutes(5));
        _cleanupTimer.Elapsed += CleanupStaleConnections;
        _cleanupTimer.AutoReset = true;
        _cleanupTimer.Start();
    }

    public SignalRConnectionLimitMiddleware(
        RequestDelegate next,
        ILogger<SignalRConnectionLimitMiddleware> logger,
        IOptions<SignalRRateLimitOptions> options)
    {
        _next = next;
        _logger = logger;
        _options = options;
    }

    public async Task InvokeAsync(HttpContext context)
    {
        var path = context.Request.Path.Value ?? "";

        // Only apply to SignalR hub endpoint
        if (!path.StartsWith("/hubs/", StringComparison.OrdinalIgnoreCase))
        {
            await _next(context);
            return;
        }

        var clientIp = GetClientIpAddress(context);

        // Check connection limit
        var currentCount = _connectionsPerIp.GetOrAdd(clientIp, 0);

        if (currentCount >= _options.Value.MaxConnectionsPerIp)
        {
            _logger.LogWarning(
                "SignalR connection limit exceeded for IP {IP}: {Count}/{Max}",
                clientIp,
                currentCount,
                _options.Value.MaxConnectionsPerIp);

            context.Response.StatusCode = StatusCodes.Status429TooManyRequests;
            context.Response.ContentType = "text/plain";
            await context.Response.WriteAsync("Too many connections. Please try again later.");
            return;
        }

        // Increment connection count
        _connectionsPerIp.AddOrUpdate(clientIp, 1, (_, current) => current + 1);

        try
        {
            await _next(context);
        }
        finally
        {
            // Decrement connection count when connection closes
            _connectionsPerIp.AddOrUpdate(clientIp, 0, (_, current) => Math.Max(0, current - 1));
        }
    }

    private static string GetClientIpAddress(HttpContext context)
    {
        // Check X-Forwarded-For header (proxy/load balancer)
        if (context.Request.Headers.TryGetValue("X-Forwarded-For", out var forwardedFor))
        {
            var firstIp = forwardedFor.FirstOrDefault()?.Split(',')[0].Trim();
            if (!string.IsNullOrEmpty(firstIp))
            {
                return firstIp;
            }
        }

        // Fallback to remote IP
        return context.Connection.RemoteIpAddress?.ToString() ?? "unknown";
    }

    private static void CleanupStaleConnections(object? sender, ElapsedEventArgs e)
    {
        // Remove IPs with zero connections
        foreach (var ip in _connectionsPerIp.Where(kvp => kvp.Value == 0).Select(kvp => kvp.Key))
        {
            _connectionsPerIp.TryRemove(ip, out _);
        }
    }
}

/// <summary>
/// Options for SignalR rate limiting
/// </summary>
public class SignalRRateLimitOptions
{
    public const string SectionName = "SignalRRateLimit";

    /// <summary>
    /// Maximum concurrent connections per IP address
    /// </summary>
    public int MaxConnectionsPerIp { get; set; } = 10;

    /// <summary>
    /// Maximum hub method invocations per minute per connection
    /// </summary>
    public int MaxInvocationsPerMinute { get; set; } = 100;
}
