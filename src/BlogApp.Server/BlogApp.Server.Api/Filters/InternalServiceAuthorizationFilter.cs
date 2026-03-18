using System.Security.Cryptography;
using System.Text;
using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.Common.Options;
using Microsoft.Extensions.Options;

namespace BlogApp.Server.Api.Filters;

public sealed class InternalServiceAuthorizationFilter(
    IOptions<InternalServiceAuthSettings> settings,
    ILogger<InternalServiceAuthorizationFilter> logger) : IEndpointFilter
{
    public async ValueTask<object?> InvokeAsync(EndpointFilterInvocationContext context, EndpointFilterDelegate next)
    {
        var authSettings = settings.Value;
        if (string.IsNullOrWhiteSpace(authSettings.ServiceKey))
        {
            logger.LogError("Internal service auth key is not configured.");
            return Results.Problem(
                title: "Internal service authentication unavailable",
                statusCode: StatusCodes.Status503ServiceUnavailable);
        }

        var providedKey = context.HttpContext.Request.Headers[authSettings.HeaderName].ToString();
        if (string.IsNullOrWhiteSpace(providedKey) || !KeysMatch(providedKey, authSettings.ServiceKey))
        {
            logger.LogWarning("Rejected internal request for {Path}", context.HttpContext.Request.Path);
            return Results.Json(
                ApiResponse<object>.FailureResult("Invalid internal service credentials."),
                statusCode: StatusCodes.Status401Unauthorized);
        }

        return await next(context);
    }

    private static bool KeysMatch(string providedKey, string expectedKey)
    {
        var providedBytes = Encoding.UTF8.GetBytes(providedKey);
        var expectedBytes = Encoding.UTF8.GetBytes(expectedKey);
        return CryptographicOperations.FixedTimeEquals(providedBytes, expectedBytes);
    }
}
