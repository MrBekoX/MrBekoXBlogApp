using System.Net;
using BlogApp.Presentation.Api.Helpers;
using Microsoft.AspNetCore.HttpOverrides;
using Microsoft.Extensions.Options;

namespace BlogApp.Presentation.Api.Security;

/// <summary>Runs after framework configuration, including its environment-enabled setup.</summary>
public sealed class TrustedForwardedHeadersConfiguration(IOptions<ApiTrustedProxySettings> settings)
    : IPostConfigureOptions<ForwardedHeadersOptions>
{
    public static bool HasValidExactPeers(ApiTrustedProxySettings value) => TryReadPeers(value.KnownProxies, out _);

    public void PostConfigure(string? name, ForwardedHeadersOptions options)
    {
        var trusted = settings.Value;
        // Disable processing before removing defaults. The enabled path refills
        // exact peers before it enables either header; no trust-all state exists.
        options.ForwardedHeaders = ForwardedHeaders.None;
        options.ForwardLimit = 1;
        options.RequireHeaderSymmetry = true;
        options.KnownProxies.Clear();
        options.KnownIPNetworks.Clear();
        if (!trusted.Enabled)
        {
            return;
        }

        if (!TryReadPeers(trusted.KnownProxies, out var peers))
        {
            throw new OptionsValidationException(ApiTrustedProxySettings.SectionName, typeof(ApiTrustedProxySettings),
                ["Enabled forwarding requires at least one exact IP address; wildcard, unspecified and network values are refused."]);
        }
        foreach (var peer in peers)
        {
            options.KnownProxies.Add(peer);
        }
        options.ForwardedHeaders = ForwardedHeaders.XForwardedFor | ForwardedHeaders.XForwardedProto;
    }

    private static bool TryReadPeers(string[]? configured, out IPAddress[] peers)
    {
        peers = [];
        if (configured is not { Length: > 0 })
        {
            return false;
        }
        var exact = new HashSet<IPAddress>();
        foreach (var value in configured)
        {
            if (string.IsNullOrWhiteSpace(value) || !IPAddress.TryParse(value.Trim(), out var parsed))
            {
                return false;
            }
            var peer = ClientIpAddress.Normalize(parsed)!;
            if (peer.Equals(IPAddress.Any) || peer.Equals(IPAddress.None)
                || peer.Equals(IPAddress.IPv6Any) || peer.Equals(IPAddress.IPv6None))
            {
                return false;
            }
            exact.Add(peer);
        }
        peers = exact.ToArray();
        return true;
    }
}
