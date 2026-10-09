namespace BlogApp.Presentation.Api.Helpers;

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
            Secure = true,
            SameSite = SameSiteMode.Lax,
            Path = "/",
            Expires = accessTokenExpiry,
            IsEssential = true
        };

        var refreshCookieOptions = new CookieOptions
        {
            HttpOnly = true,
            Secure = true,
            SameSite = SameSiteMode.Lax,
            Path = "/",
            Expires = DateTime.UtcNow.AddDays(7),
            IsEssential = true
        };

        // Use simple cookie name for frontend compatibility
        response.Cookies.Append("accessToken", accessToken, accessCookieOptions);
        response.Cookies.Append("refreshToken", refreshToken, refreshCookieOptions);
    }

    public static void ClearAuthCookies(HttpResponse response, bool isProduction)
    {
        response.Cookies.Delete("accessToken", new CookieOptions
        {
            HttpOnly = true,
            Secure = true,
            SameSite = SameSiteMode.Lax,
            Path = "/"
        });

        response.Cookies.Delete("refreshToken", new CookieOptions
        {
            HttpOnly = true,
            Secure = true,
            SameSite = SameSiteMode.Lax,
            Path = "/"
        });
    }

    public static string? GetIpAddress(HttpContext context)
    {
        // Use RemoteIpAddress which is already set correctly by ForwardedHeaders middleware
        return context.Connection.RemoteIpAddress?.MapToIPv4().ToString();
    }
}

