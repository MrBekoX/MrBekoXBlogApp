using AspNetCoreRateLimit;
using BlogApp.Presentation.Api.Helpers;
using Microsoft.Extensions.Options;

namespace BlogApp.Presentation.Api.Security;

/// <summary>Use the validated connection identity; raw request headers are never resolvers.</summary>
public sealed class CanonicalIpRateLimitConfiguration(
    IOptions<IpRateLimitOptions> ipOptions,
    IOptions<ClientRateLimitOptions> clientOptions) : RateLimitConfiguration(ipOptions, clientOptions)
{
    public override void RegisterResolvers()
    {
        IpResolvers.Clear();
        ClientResolvers.Clear();
        IpResolvers.Add(new CanonicalConnectionIpContributor());
    }

    private sealed class CanonicalConnectionIpContributor : IIpResolveContributor
    {
        public string ResolveIp(HttpContext context) => ClientIpAddress.Get(context) ?? "unknown";
    }
}
