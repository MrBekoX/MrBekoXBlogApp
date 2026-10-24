using System.Net;

namespace BlogApp.Presentation.Api.Helpers;

/// <summary>Canonical identity after the trusted forwarding middleware has run.</summary>
public static class ClientIpAddress
{
    public static IPAddress? Normalize(IPAddress? address) =>
        address is { IsIPv4MappedToIPv6: true } ? address.MapToIPv4() : address;

    public static string? Get(HttpContext context) => Normalize(context.Connection.RemoteIpAddress)?.ToString();
}
