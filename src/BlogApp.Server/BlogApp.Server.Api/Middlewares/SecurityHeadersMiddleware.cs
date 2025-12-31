namespace BlogApp.Server.Api.Middlewares;

/// <summary>
/// Adds security headers to all responses to protect against common web vulnerabilities.
/// </summary>
public class SecurityHeadersMiddleware(RequestDelegate next)
{
    public async Task InvokeAsync(HttpContext context)
    {
        // Prevent MIME type sniffing
        context.Response.Headers.Append("X-Content-Type-Options", "nosniff");

        // Prevent clickjacking attacks
        context.Response.Headers.Append("X-Frame-Options", "DENY");

        // Enable XSS filter in browsers (legacy but still useful)
        context.Response.Headers.Append("X-XSS-Protection", "1; mode=block");

        // Prevent information leakage via referrer
        context.Response.Headers.Append("Referrer-Policy", "strict-origin-when-cross-origin");

        // Restrict browser features
        context.Response.Headers.Append("Permissions-Policy", "accelerometer=(), camera=(), geolocation=(), gyroscope=(), magnetometer=(), microphone=(), payment=(), usb=()");

        // Content Security Policy - adjust based on your frontend needs
        context.Response.Headers.Append("Content-Security-Policy", "default-src 'self'; img-src 'self' data: https:; style-src 'self' 'unsafe-inline'; script-src 'self'; frame-ancestors 'none';");

        await next(context);
    }
}

public static class SecurityHeadersMiddlewareExtensions
{
    public static IApplicationBuilder UseSecurityHeaders(this IApplicationBuilder app)
    {
        return app.UseMiddleware<SecurityHeadersMiddleware>();
    }
}

