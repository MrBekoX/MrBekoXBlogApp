using System.Diagnostics;

namespace BlogApp.Server.Api.Middlewares;

/// <summary>
/// Request logging middleware
/// </summary>
public class RequestLoggingMiddleware
{
    private readonly RequestDelegate _next;
    private readonly ILogger<RequestLoggingMiddleware> _logger;

    public RequestLoggingMiddleware(RequestDelegate next, ILogger<RequestLoggingMiddleware> logger)
    {
        _next = next;
        _logger = logger;
    }

    public async Task InvokeAsync(HttpContext context)
    {
        var correlationId = context.TraceIdentifier;
        var stopwatch = Stopwatch.StartNew();

        var method = context.Request.Method;
        var path = context.Request.Path;
        var queryString = context.Request.QueryString;

        _logger.LogInformation(
            "[{CorrelationId}] {Method} {Path}{QueryString} - Started",
            correlationId, method, path, queryString);

        await _next(context);

        stopwatch.Stop();

        var statusCode = context.Response.StatusCode;
        var elapsed = stopwatch.ElapsedMilliseconds;

        var logLevel = statusCode >= 500 ? LogLevel.Error :
                       statusCode >= 400 ? LogLevel.Warning : LogLevel.Information;

        _logger.Log(
            logLevel,
            "[{CorrelationId}] {Method} {Path} - {StatusCode} in {Elapsed}ms",
            correlationId, method, path, statusCode, elapsed);
    }
}

public static class RequestLoggingMiddlewareExtensions
{
    public static IApplicationBuilder UseRequestLogging(this IApplicationBuilder builder)
    {
        return builder.UseMiddleware<RequestLoggingMiddleware>();
    }
}
