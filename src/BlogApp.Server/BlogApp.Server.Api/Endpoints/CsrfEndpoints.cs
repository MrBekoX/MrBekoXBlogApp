using Microsoft.AspNetCore.Antiforgery;

namespace BlogApp.Server.Api.Endpoints;

/// <summary>
/// CSRF token endpoints for SPA clients
/// </summary>
public static class CsrfEndpoints
{
    public static IEndpointRouteBuilder RegisterCsrfEndpoints(this IEndpointRouteBuilder app)
    {
        var versionedGroup = app.NewVersionedApi("Csrf");
        var group = versionedGroup.MapGroup("/api/v{version:apiVersion}")
            .HasApiVersion(1.0)
            .WithTags("CSRF");

        // GET /api/v1/csrf-token
        group.MapGet("/csrf-token", (IAntiforgery antiforgery, HttpContext context) =>
        {
            // Generate CSRF tokens and set cookie
            var tokens = antiforgery.GetAndStoreTokens(context);
            
            // Also expose token in response header for SPA to read
            context.Response.Headers.Append("X-CSRF-TOKEN", tokens.RequestToken!);
            
            return Results.Ok(new 
            { 
                message = "CSRF token generated",
                // Token is also available in X-CSRF-TOKEN response header
                // and BlogApp.CSRF cookie (HttpOnly)
            });
        })
        .WithName("GetCsrfToken")
        .WithDescription("Get CSRF token for subsequent state-changing requests")
        .Produces(200);

        return app;
    }
}

