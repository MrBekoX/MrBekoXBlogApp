using System.Net;
using AspNetCoreRateLimit;
using BlogApp.Presentation.Api.Extensions;
using BlogApp.Presentation.Api.Helpers;
using BlogApp.Presentation.Api.Middlewares;
using BlogApp.Presentation.Api.Security;
using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.DataProtection;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.HttpOverrides;
using Microsoft.AspNetCore.TestHost;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Options;
using Xunit;

namespace BlogApp.Presentation.Api.Tests.Security;

/// <summary>Real ASP.NET forwarding/rate-limit middleware without application databases or AI.</summary>
public sealed class TrustedClientIpTests
{
    private const string Proxy = "192.0.2.10";
    private const string Direct = "198.51.100.20";
    private const string Client = "203.0.113.21";
    private const string Allowlisted = "203.0.113.200";

    private static async Task<WebApplication> StartAsync(bool enabled = true, string? configuredPeer = Proxy,
        bool automaticForwarding = true, bool legacyBoundary = false, bool signalR = false,
        bool explicitForwarding = true,
        RequestDelegate? terminal = null)
    {
        var builder = WebApplication.CreateBuilder(new WebApplicationOptions
        {
            EnvironmentName = "Testing",
            ApplicationName = typeof(TrustedClientIpTests).Assembly.FullName,
        });
        builder.WebHost.UseTestServer();
        // This is the host setting loaded from ASPNETCORE_FORWARDEDHEADERS_ENABLED.
        builder.WebHost.UseSetting("forwardedHeaders_enabled", automaticForwarding ? "true" : "false");
        builder.Configuration.AddInMemoryCollection(new Dictionary<string, string?>
        {
            ["ForwardedHeaders:Enabled"] = enabled.ToString(),
            ["ForwardedHeaders:KnownProxies:0"] = configuredPeer,
            ["IpRateLimiting:EnableEndpointRateLimiting"] = "true",
            ["IpRateLimiting:RealIpHeader"] = "X-Real-IP",
            ["IpRateLimiting:ClientIdHeader"] = "X-ClientId",
            ["IpRateLimiting:ClientWhitelist:0"] = "trusted-client",
            ["IpRateLimiting:IpWhitelist:0"] = Allowlisted,
            ["IpRateLimiting:HttpStatusCode"] = "429",
            ["IpRateLimiting:GeneralRules:0:Endpoint"] = "post:/api/v1/auth/login",
            ["IpRateLimiting:GeneralRules:0:Period"] = "1m",
            ["IpRateLimiting:GeneralRules:0:Limit"] = "5",
        });
        if (!legacyBoundary)
        {
            builder.Services.AddTrustedProxyForwarding(builder.Configuration);
        }
        builder.Services.AddSecurityServices(builder.Configuration, builder.Environment);
        builder.Services.AddDataProtection().UseEphemeralDataProtectionProvider();
        if (legacyBoundary)
        {
            // Executable baseline of the original shared boundary, isolated to TestServer.
            builder.Services.AddSingleton<IRateLimitConfiguration, RateLimitConfiguration>();
            builder.Services.Configure<ForwardedHeadersOptions>(options =>
            {
                options.ForwardedHeaders = ForwardedHeaders.XForwardedFor | ForwardedHeaders.XForwardedProto;
                options.ForwardLimit = 2;
                options.KnownProxies.Clear();
                options.KnownIPNetworks.Clear();
            });
        }
        if (signalR)
        {
            builder.Services.Configure<SignalRRateLimitOptions>(options => options.MaxConnectionsPerIp = 1);
        }
        var app = builder.Build();
        if (explicitForwarding)
        {
            app.UseForwardedHeaders();
        }
        if (signalR)
        {
            app.UseMiddleware<SignalRConnectionLimitMiddleware>();
        }
        SecurityExtensions.UseIpRateLimiting(app);
        app.Run(terminal ?? (context =>
        {
            context.Items["canonical-ip"] = ClientIpAddress.Get(context);
            context.Items["cookie-ip"] = CookieHelper.GetIpAddress(context);
            context.Items["scheme"] = context.Request.Scheme;
            return context.Response.WriteAsync("identity inspected");
        }));
        try
        {
            await app.StartAsync();
            return app;
        }
        catch
        {
            await app.DisposeAsync();
            throw;
        }
    }

    private static Task<HttpContext> SendAsync(WebApplication app, string peer, string? forwardedFor = null,
        string? forwardedProto = null, string? rawIp = null, string? clientId = null,
        string path = "/api/v1/auth/login") => app.GetTestServer().SendAsync(context =>
    {
        // A real transport supplies this before any automatic startup-filter middleware.
        context.Connection.RemoteIpAddress = IPAddress.Parse(peer);
        context.Connection.RemotePort = 41000;
        context.Request.Method = HttpMethods.Post;
        context.Request.Path = path;
        context.Request.Scheme = "http";
        context.Request.Host = new HostString("blog.test");
        if (forwardedFor is not null) context.Request.Headers["X-Forwarded-For"] = forwardedFor;
        if (forwardedProto is not null) context.Request.Headers["X-Forwarded-Proto"] = forwardedProto;
        if (rawIp is not null) context.Request.Headers["X-Real-IP"] = rawIp;
        if (clientId is not null) context.Request.Headers["X-ClientId"] = clientId;
    });

    [Fact]
    public async Task OriginalBoundary_ReproducesSpoofedIdentityAndClientWhitelistBypass()
    {
        await using var app = await StartAsync(legacyBoundary: true);
        for (var request = 0; request < 6; request++)
        {
            var response = await SendAsync(app, Direct, Client, "https", Allowlisted, "trusted-client");
            Assert.Equal(StatusCodes.Status200OK, response.Response.StatusCode);
            Assert.Equal(Client, response.Items["canonical-ip"]);
            Assert.Equal("https", response.Items["scheme"]);
        }
    }

    [Fact]
    public async Task AutomaticStartupFilter_UsesTheSameGlobalTrustPolicy()
    {
        // The baseline verifies that the framework's automatic filter really
        // runs here; the hardened controls do not rely on explicit middleware.
        await using (var baseline = await StartAsync(legacyBoundary: true, explicitForwarding: false))
        {
            var spoofed = await SendAsync(baseline, Direct, Client, "https");
            Assert.Equal(Client, spoofed.Items["canonical-ip"]);
            Assert.Equal("https", spoofed.Items["scheme"]);
        }
        await using (var disabled = await StartAsync(enabled: false, configuredPeer: null, explicitForwarding: false))
        {
            var direct = await SendAsync(disabled, Direct, Client, "https", Allowlisted, "trusted-client");
            Assert.Equal(Direct, direct.Items["canonical-ip"]);
            Assert.Equal("http", direct.Items["scheme"]);
            Assert.Equal(ForwardedHeaders.None,
                disabled.Services.GetRequiredService<IOptions<ForwardedHeadersOptions>>().Value.ForwardedHeaders);
        }
        await using (var known = await StartAsync(explicitForwarding: false))
        {
            var accepted = await SendAsync(known, Proxy, Client, "https");
            Assert.Equal(Client, accepted.Items["canonical-ip"]);
            Assert.Equal("https", accepted.Items["scheme"]);
        }
    }

    [Theory]
    [InlineData(false, false)]
    [InlineData(false, true)]
    [InlineData(true, false)]
    [InlineData(true, true)]
    public async Task UnknownPeers_CannotSpoofIdentitySchemeWhitelistOrResetQuota(bool enabled, bool automatic)
    {
        await using var app = await StartAsync(enabled: enabled, automaticForwarding: automatic);
        for (var request = 0; request < 5; request++)
        {
            var response = await SendAsync(app, Direct, $"203.0.113.{30 + request}", "https",
                request % 2 == 0 ? Allowlisted : "malformed-ip", "trusted-client");
            Assert.Equal(StatusCodes.Status200OK, response.Response.StatusCode);
            Assert.Equal(Direct, response.Items["canonical-ip"]);
            Assert.Equal(Direct, response.Items["cookie-ip"]);
            Assert.Equal("http", response.Items["scheme"]);
        }
        var blocked = await SendAsync(app, Direct, "203.0.113.99", "https", Allowlisted, "trusted-client");
        Assert.Equal(StatusCodes.Status429TooManyRequests, blocked.Response.StatusCode);
    }

    [Theory]
    [InlineData(Proxy, Proxy)]
    [InlineData("::ffff:192.0.2.10", Proxy)]
    [InlineData(Proxy, "::ffff:192.0.2.10")]
    [InlineData("2001:db8::10", "2001:db8::10")]
    public async Task ExactKnownProxy_AcceptsCanonicalClientAndScheme(string actualPeer, string configuredPeer)
    {
        await using var app = await StartAsync(configuredPeer: configuredPeer);
        var response = await SendAsync(app, actualPeer, "::ffff:203.0.113.21", "https", "not-an-ip", "trusted-client");
        Assert.Equal(StatusCodes.Status200OK, response.Response.StatusCode);
        Assert.Equal(Client, response.Items["canonical-ip"]);
        Assert.Equal(Client, response.Items["cookie-ip"]);
        Assert.Equal("https", response.Items["scheme"]);
        var options = app.Services.GetRequiredService<IOptions<ForwardedHeadersOptions>>().Value;
        Assert.Equal(1, options.ForwardLimit);
        Assert.True(options.RequireHeaderSymmetry);
        Assert.Empty(options.KnownIPNetworks);
        Assert.Single(options.KnownProxies);
    }

    [Theory]
    [InlineData("malformed", "https")]
    [InlineData(Client, null)]
    [InlineData(null, "https")]
    [InlineData(Client, "https,http")]
    [InlineData(Client, "https://invalid.test")]
    public async Task MalformedOrAsymmetricForwarding_RemainsDirect(string? forwardedFor, string? forwardedProto)
    {
        await using var app = await StartAsync();
        var response = await SendAsync(app, Proxy, forwardedFor, forwardedProto);
        Assert.Equal(StatusCodes.Status200OK, response.Response.StatusCode);
        Assert.Equal(Proxy, response.Items["canonical-ip"]);
        Assert.Equal("http", response.Items["scheme"]);
    }

    [Fact]
    public async Task SingleHop_ConsumesOnlyRightmostPair_WhenAutomaticAndExplicitMiddlewareArePresent()
    {
        await using var app = await StartAsync();
        var response = await SendAsync(app, Proxy, "198.51.100.90,203.0.113.21", "http,https");
        Assert.Equal(Client, response.Items["canonical-ip"]);
        Assert.Equal("https", response.Items["scheme"]);
    }

    [Fact]
    public async Task LegitimateClientsBehindOneProxy_HaveSeparateQuotas()
    {
        await using var app = await StartAsync();
        foreach (var client in new[] { Client, "203.0.113.22" })
        {
            for (var request = 0; request < 5; request++)
            {
                Assert.Equal(StatusCodes.Status200OK, (await SendAsync(app, Proxy, client, "https")).Response.StatusCode);
            }
        }
        Assert.Equal(StatusCodes.Status429TooManyRequests, (await SendAsync(app, Proxy, Client, "https")).Response.StatusCode);
    }

    [Theory]
    [InlineData("2001:db8:aaaa::1")]
    [InlineData("2001:db8:bbbb::1")]
    public async Task KnownProxy_PreservesNativeIPv6ClientMetadata(string client)
    {
        await using var app = await StartAsync();
        var response = await SendAsync(app, Proxy, client, "https");
        Assert.Equal(StatusCodes.Status200OK, response.Response.StatusCode);
        Assert.Equal(client, response.Items["canonical-ip"]);
        Assert.Equal(client, response.Items["cookie-ip"]);
    }

    [Fact]
    public async Task MappedAndPlainIPv4_ShareQuota_WhileNativeIPv6RemainsDistinct()
    {
        await using var app = await StartAsync(enabled: false);
        for (var request = 0; request < 5; request++)
        {
            var peer = request % 2 == 0 ? Client : "::ffff:203.0.113.21";
            var response = await SendAsync(app, peer);
            Assert.Equal(Client, response.Items["canonical-ip"]);
            Assert.Equal(Client, response.Items["cookie-ip"]);
        }
        Assert.Equal(StatusCodes.Status429TooManyRequests, (await SendAsync(app, Client)).Response.StatusCode);
        foreach (var peer in new[] { "2001:db8:aaaa::1", "2001:db8:bbbb::1" })
        {
            for (var request = 0; request < 5; request++)
            {
                var response = await SendAsync(app, peer);
                Assert.Equal(StatusCodes.Status200OK, response.Response.StatusCode);
                Assert.Equal(peer, response.Items["canonical-ip"]);
                Assert.Equal(peer, response.Items["cookie-ip"]);
            }
        }
    }

    [Fact]
    public async Task GenuineIpWhitelist_RemainsUsableThroughKnownProxy()
    {
        await using var app = await StartAsync();
        for (var request = 0; request < 7; request++)
        {
            Assert.Equal(StatusCodes.Status200OK,
                (await SendAsync(app, Proxy, Allowlisted, "https")).Response.StatusCode);
        }
    }

    [Fact]
    public async Task SignalR_UsesTheSameMappedIPv4Identity()
    {
        var entered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var release = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        await using var app = await StartAsync(enabled: false, signalR: true, terminal: async context =>
        {
            entered.TrySetResult();
            await release.Task.WaitAsync(TimeSpan.FromSeconds(10));
            await context.Response.WriteAsync("closed");
        });
        var active = SendAsync(app, "::ffff:203.0.113.81", path: "/hubs/test");
        try
        {
            await entered.Task.WaitAsync(TimeSpan.FromSeconds(5));
            var blocked = await SendAsync(app, "203.0.113.81", path: "/hubs/test");
            Assert.Equal(StatusCodes.Status429TooManyRequests, blocked.Response.StatusCode);
        }
        finally
        {
            release.TrySetResult();
            await active;
        }
    }

    [Theory]
    [InlineData(null)]
    [InlineData("")]
    [InlineData("not-an-ip")]
    [InlineData("192.0.2.0/24")]
    [InlineData("0.0.0.0")]
    [InlineData("::")]
    [InlineData("255.255.255.255")]
    [InlineData("::ffff:0.0.0.0")]
    public async Task EnabledWithoutValidExactPeer_RefusesStartup(string? peer)
    {
        await Assert.ThrowsAnyAsync<OptionsValidationException>(() => StartAsync(configuredPeer: peer));
    }
}
