namespace BlogApp.Server.Api.Helpers;

public static class CookieHelper
{
    public static void SetAuthCookies(
        HttpResponse response,
        string accessToken,
        string refreshToken,
        DateTime accessTokenExpiry,
        bool isProduction)
    {
        var accessCookieOptions = new CookieOptions
        {
            HttpOnly = true,
            Secure = isProduction,
            SameSite = SameSiteMode.Strict,
            Path = "/api",
            Expires = accessTokenExpiry,
            IsEssential = true
        };

        var refreshCookieOptions = new CookieOptions
        {
            HttpOnly = true,
            Secure = isProduction,
            SameSite = SameSiteMode.Strict,
            Path = "/api/auth",
            Expires = DateTime.UtcNow.AddDays(7),
            IsEssential = true
        };

        response.Cookies.Append("BlogApp.AccessToken", accessToken, accessCookieOptions);
        response.Cookies.Append("BlogApp.RefreshToken", refreshToken, refreshCookieOptions);
    }

    public static void ClearAuthCookies(HttpResponse response, bool isProduction)
    {
        response.Cookies.Delete("BlogApp.AccessToken", new CookieOptions
        {
            HttpOnly = true,
            Secure = isProduction,
            SameSite = SameSiteMode.Strict,
            Path = "/api"
        });

        response.Cookies.Delete("BlogApp.RefreshToken", new CookieOptions
        {
            HttpOnly = true,
            Secure = isProduction,
            SameSite = SameSiteMode.Strict,
            Path = "/api/auth"
        });
    }

    public static string? GetIpAddress(HttpContext context)
    {
        if (context.Request.Headers.TryGetValue("X-Forwarded-For", out var forwardedFor))
            return forwardedFor.FirstOrDefault();

        return context.Connection.RemoteIpAddress?.MapToIPv4().ToString();
    }
}
