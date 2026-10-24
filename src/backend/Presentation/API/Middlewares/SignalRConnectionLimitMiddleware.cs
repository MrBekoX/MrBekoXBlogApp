using BlogApp.Presentation.Api.Helpers;
using BlogApp.Presentation.Api.Security;
using Microsoft.Extensions.Options;

namespace BlogApp.Presentation.Api.Middlewares;

/// <summary>Atomic, bounded connection admission for all SignalR transports.</summary>
public sealed class SignalRConnectionLimitMiddleware(
    RequestDelegate next,
    SignalRAdmissionControl admission,
    IOptions<SignalRRateLimitOptions> options)
{
    public async Task InvokeAsync(HttpContext context)
    {
        if (!context.Request.Path.StartsWithSegments("/hubs", StringComparison.OrdinalIgnoreCase))
        {
            await next(context);
            return;
        }
        var ip = ClientIpAddress.Get(context) ?? "unknown";
        if (!admission.TryAcquireConnection(ip, options.Value, out var lease))
        {
            context.Response.StatusCode = StatusCodes.Status429TooManyRequests;
            context.Response.Headers.RetryAfter = "1";
            await context.Response.WriteAsync("Too many connections. Please try again later.");
            return;
        }
        using (lease) await next(context);
    }
}

public sealed class SignalRRateLimitOptions
{
    public const string SectionName = "SignalRRateLimit";
    public int MaxConnectionsPerIp { get; set; } = 10;
    public int MaxConnectionsTotal { get; set; } = 256;
    public int MaxInvocationsPerMinute { get; set; } = 100;
    public int MaxTrackedSubjects { get; set; } = 4096;
}
