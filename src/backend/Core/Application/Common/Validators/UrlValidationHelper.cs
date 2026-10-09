using System.Net;
using System.Net.Sockets;

namespace BlogApp.Core.Application.Common.Validators;

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

        var host = uri.Host.ToLowerInvariant();

        // Metadata endpoints engelle (cloud providers)
        if (host == "metadata.google.internal")
            return false;

        // Localhost engelle
        if (host == "localhost")
            return false;

        // IP adresini parse edip binary seviyede kontrol et
        // Bu octal (0177.0.0.1), hex (0x7f000001) ve IPv6 temsillerini de yakalar
        if (IPAddress.TryParse(uri.Host, out var ipAddress))
            return !IsPrivateOrReservedIp(ipAddress);

        return true;
    }

    private static bool IsPrivateOrReservedIp(IPAddress ip)
    {
        // IPv4-mapped IPv6 adreslerini IPv4'e cevir
        if (ip.IsIPv4MappedToIPv6)
            ip = ip.MapToIPv4();

        var bytes = ip.GetAddressBytes();

        if (ip.AddressFamily == AddressFamily.InterNetwork)
        {
            // 0.0.0.0/8 — current network
            if (bytes[0] == 0) return true;

            // 10.0.0.0/8 — RFC 1918
            if (bytes[0] == 10) return true;

            // 127.0.0.0/8 — loopback
            if (bytes[0] == 127) return true;

            // 169.254.0.0/16 — link-local + cloud metadata (169.254.169.254)
            if (bytes[0] == 169 && bytes[1] == 254) return true;

            // 172.16.0.0/12 — RFC 1918
            if (bytes[0] == 172 && bytes[1] >= 16 && bytes[1] <= 31) return true;

            // 192.168.0.0/16 — RFC 1918
            if (bytes[0] == 192 && bytes[1] == 168) return true;

            return false;
        }

        if (ip.AddressFamily == AddressFamily.InterNetworkV6)
        {
            // ::1 — loopback
            if (IPAddress.IsLoopback(ip)) return true;

            // :: — unspecified
            if (ip.Equals(IPAddress.IPv6None)) return true;

            // fc00::/7 — unique local (ULA)
            if ((bytes[0] & 0xFE) == 0xFC) return true;

            // fe80::/10 — link-local
            if (bytes[0] == 0xFE && (bytes[1] & 0xC0) == 0x80) return true;

            return false;
        }

        return true;
    }
}
