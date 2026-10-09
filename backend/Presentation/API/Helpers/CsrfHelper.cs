using Microsoft.AspNetCore.Antiforgery;

namespace BlogApp.Presentation.Api.Helpers;

/// <summary>
/// CSRF token generation helper for SPA clients.
/// </summary>
public static class CsrfHelper
{
    /// <summary>
    /// Generates CSRF tokens, stores them in a cookie, and returns the request token.
    /// </summary>
    public static string GenerateAndStoreToken(IAntiforgery antiforgery, HttpContext context)
    {
        var tokens = antiforgery.GetAndStoreTokens(context);
        context.Response.Headers.Append("X-CSRF-TOKEN", tokens.RequestToken!);
        return tokens.RequestToken!;
    }
}
