namespace BlogApp.Server.Application.Common.Validators;

/// <summary>
/// Shared URL validation helper for SSRF prevention.
/// </summary>
public static class UrlValidationHelper
{
    /// <summary>
    /// URL'in geçerli ve güvenli olup olmadığını kontrol eder.
    /// SSRF saldırılarını önlemek için internal IP'lere erişimi engeller.
    /// </summary>
    public static bool BeAValidAndSafeUrl(string? url)
    {
        if (string.IsNullOrEmpty(url))
            return true;

        // Relative URL'lere izin ver (/uploads/... gibi)
        if (url.StartsWith('/'))
            return true;

        if (!Uri.TryCreate(url, UriKind.Absolute, out var uri))
            return false;

        // Sadece HTTP/HTTPS'e izin ver
        if (uri.Scheme != Uri.UriSchemeHttp && uri.Scheme != Uri.UriSchemeHttps)
            return false;

        // SSRF Prevention: Internal IP adreslerini engelle
        var host = uri.Host.ToLowerInvariant();

        // Localhost engelle
        if (host == "localhost" || host == "127.0.0.1" || host == "::1" || host == "[::1]")
            return false;

        // Private IP ranges engelle (RFC 1918)
        if (host.StartsWith("192.168.") || host.StartsWith("10.") || host.StartsWith("172.16.") ||
            host.StartsWith("172.17.") || host.StartsWith("172.18.") || host.StartsWith("172.19.") ||
            host.StartsWith("172.20.") || host.StartsWith("172.21.") || host.StartsWith("172.22.") ||
            host.StartsWith("172.23.") || host.StartsWith("172.24.") || host.StartsWith("172.25.") ||
            host.StartsWith("172.26.") || host.StartsWith("172.27.") || host.StartsWith("172.28.") ||
            host.StartsWith("172.29.") || host.StartsWith("172.30.") || host.StartsWith("172.31."))
            return false;

        // Link-local addresses engelle
        if (host.StartsWith("169.254."))
            return false;

        // Metadata endpoints engelle (cloud providers)
        if (host == "169.254.169.254" || host == "metadata.google.internal")
            return false;

        return true;
    }
}
