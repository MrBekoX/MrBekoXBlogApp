using System.Security.Claims;
using BlogApp.Server.Application.Common.Interfaces.Services;
using Microsoft.AspNetCore.Http;

namespace BlogApp.Server.Infrastructure.Services;

/// <summary>
/// Mevcut kullanıcı bilgisi servisi implementasyonu
/// </summary>
public class CurrentUserService(IHttpContextAccessor httpContextAccessor) : ICurrentUserService
{
    public Guid? UserId
    {
        get
        {
            // Fix: Add explicit null check for HttpContext
            var httpContext = httpContextAccessor.HttpContext;
            if (httpContext == null)
            {
                return null;
            }

            var userIdClaim = httpContext.User?.FindFirst("userId")
                              ?? httpContext.User?.FindFirst(ClaimTypes.NameIdentifier);

            if (userIdClaim is not null && Guid.TryParse(userIdClaim.Value, out var userId))
            {
                return userId;
            }

            return null;
        }
    }

    public string? CorrelationId =>
        httpContextAccessor.HttpContext?.TraceIdentifier;

    public string? UserName =>
        httpContextAccessor.HttpContext?.User?.FindFirst(ClaimTypes.Name)?.Value;

    public string? Email =>
        httpContextAccessor.HttpContext?.User?.FindFirst(ClaimTypes.Email)?.Value;

    public bool IsAuthenticated =>
        httpContextAccessor.HttpContext?.User?.Identity?.IsAuthenticated ?? false;

    public bool IsInRole(string role)
    {
        return httpContextAccessor.HttpContext?.User?.IsInRole(role) ?? false;
    }
}
