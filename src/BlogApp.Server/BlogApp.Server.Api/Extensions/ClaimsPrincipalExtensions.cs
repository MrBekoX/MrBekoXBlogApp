using System.Security.Claims;
using BlogApp.Server.Application.Common.Security;

namespace BlogApp.Server.Api.Extensions;

public static class ClaimsPrincipalExtensions
{
    public static Guid? GetUserId(this ClaimsPrincipal? principal)
    {
        if (principal?.Identity?.IsAuthenticated != true)
        {
            return null;
        }

        var userIdValue = principal.FindFirst("userId")?.Value
            ?? principal.FindFirst(ClaimTypes.NameIdentifier)?.Value;

        return Guid.TryParse(userIdValue, out var userId)
            ? userId
            : null;
    }

    public static PostAuthorizationSubject ToPostAuthorizationSubject(this ClaimsPrincipal? principal)
    {
        if (principal?.Identity?.IsAuthenticated != true)
        {
            return PostAuthorizationSubject.Anonymous;
        }

        var roles = principal.FindAll(ClaimTypes.Role)
            .Concat(principal.FindAll("role"))
            .Select(claim => claim.Value)
            .Where(value => !string.IsNullOrWhiteSpace(value))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToArray();

        return new PostAuthorizationSubject(
            principal.GetUserId(),
            true,
            roles);
    }
}
