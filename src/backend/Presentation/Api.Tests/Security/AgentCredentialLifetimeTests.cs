using System.Globalization;
using System.IdentityModel.Tokens.Jwt;
using System.Net;
using System.Net.Http.Headers;
using System.Net.WebSockets;
using System.Security.Claims;
using System.Text;
using BlogApp.Core.Application.Common.Interfaces.Services;
using BlogApp.Core.Application.Common.Interfaces.Data;
using BlogApp.Core.Application.Common.Options;
using BlogApp.Core.Domain.Entities;
using BlogApp.Infrastructure.Services;
using BlogApp.Infrastructure.Persistence;
using BlogApp.Presentation.Api.Extensions;
using BlogApp.Presentation.Api.Hubs;
using BlogApp.Presentation.Api.Security;
using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.TestHost;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging.Abstractions;
using Microsoft.Extensions.Options;
using Microsoft.EntityFrameworkCore;
using Microsoft.IdentityModel.Tokens;
using Xunit;

namespace BlogApp.Presentation.Api.Tests.Security;

public sealed class AgentCredentialLifetimeTests
{
    internal const string SigningKey = "isolated-jwt-lifetime-test-key-01234567890123456789";
    internal static readonly JwtSettings Settings = new()
    {
        Secret = SigningKey, Issuer = "lifetime-tests", Audience = "lifetime-tests",
    };

    [Fact]
    public void GeneratedTokenCarriesStandardAndPreciseIssuanceTimes()
    {
        var token = new JwtSecurityTokenHandler().ReadJwtToken(Generate(Guid.NewGuid()));
        var seconds = long.Parse(token.Claims.Single(claim => claim.Type == "iat").Value, CultureInfo.InvariantCulture);
        var ticks = long.Parse(token.Claims.Single(claim => claim.Type == "issued_at_ticks").Value, CultureInfo.InvariantCulture);
        Assert.Equal(seconds, new DateTimeOffset(ticks, TimeSpan.Zero).ToUnixTimeSeconds());
    }

    [Fact]
    public async Task ActualGeneratedTokenIsRejectedAfterAccountRevocationAndFreshLoginStillWorks()
    {
        var owner = Guid.NewGuid();
        var blacklist = new MutableTokenBlacklist();
        await using var app = BuildApi(blacklist);
        await app.StartAsync();
        var client = app.GetTestClient();
        var oldToken = Generate(owner);
        Assert.Equal(HttpStatusCode.OK, await Status(client, oldToken));

        await blacklist.InvalidateAllUserTokensAsync(owner);
        Assert.Equal(HttpStatusCode.Unauthorized, await Status(client, oldToken));
        // A new login may happen within the same NumericDate second as revocation.
        Assert.Equal(HttpStatusCode.OK, await Status(client, Generate(owner)));
    }

    [Theory]
    [InlineData("userId")]
    [InlineData("UserId")]
    [InlineData(ClaimTypes.NameIdentifier)]
    public async Task LegacyTokenWithoutIatWorksUntilItsAccountIsRevoked(string userClaim)
    {
        var owner = Guid.NewGuid();
        var blacklist = new MutableTokenBlacklist();
        await using var app = BuildApi(blacklist);
        await app.StartAsync();
        var client = app.GetTestClient();
        var token = Legacy(owner, userClaim);
        Assert.Equal(HttpStatusCode.OK, await Status(client, token));
        await blacklist.InvalidateAllUserTokensAsync(owner);
        Assert.Equal(HttpStatusCode.Unauthorized, await Status(client, token));
    }

    [Fact]
    public async Task IndividualJtiRevocationContinuesToRejectTheToken()
    {
        var owner = Guid.NewGuid();
        var blacklist = new MutableTokenBlacklist();
        await using var app = BuildApi(blacklist);
        await app.StartAsync();
        var token = Generate(owner);
        var jti = new JwtSecurityTokenHandler().ReadJwtToken(token).Id;
        await blacklist.BlacklistTokenAsync(jti, TimeSpan.FromMinutes(5));
        Assert.Equal(HttpStatusCode.Unauthorized, await Status(app.GetTestClient(), token));
    }

    [Fact]
    public async Task ProductionHubMappingClosesTheSocketWhenItsJwtExpires()
    {
        var builder = WebApplication.CreateBuilder();
        builder.WebHost.UseTestServer();
        builder.Services.AddSingleton<ITokenBlacklistService>(new MutableTokenBlacklist());
        builder.Services.AddJwtAuthentication(Configuration());
        builder.Services.AddAgentSignalRAdmission(Configuration());
        // No run is subscribed or queried in this lifetime test. No database
        // provider/connection is configured, so an accidental query fails.
        builder.Services.AddScoped<IApplicationDbContext>(_ =>
            new AppDbContext(new DbContextOptionsBuilder<AppDbContext>().Options));
        await using var app = builder.Build();
        app.UseWebSockets();
        app.UseAuthentication();
        app.UseAuthorization();
        app.MapAgentRunsHub();
        await app.StartAsync();

        var token = new JwtSecurityTokenHandler().WriteToken(new JwtSecurityToken(Settings.Issuer, Settings.Audience,
            [new Claim("userId", Guid.NewGuid().ToString("D")), new Claim("jti", Guid.NewGuid().ToString("D"))],
            expires: DateTime.UtcNow.AddSeconds(2),
            signingCredentials: new SigningCredentials(new SymmetricSecurityKey(Encoding.UTF8.GetBytes(SigningKey)),
                SecurityAlgorithms.HmacSha256)));
        var client = app.GetTestServer().CreateWebSocketClient();
        client.ConfigureRequest = request => request.Headers["Authorization"] = "Bearer " + token;
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        using var socket = await client.ConnectAsync(new Uri("ws://localhost" + AgentRunsHub.HubPath), timeout.Token);
        await socket.SendAsync(new ArraySegment<byte>(Encoding.UTF8.GetBytes("{\"protocol\":\"json\",\"version\":1}\u001e")),
            WebSocketMessageType.Text, true, timeout.Token);
        var buffer = new byte[1024];
        while (true)
        {
            var result = await socket.ReceiveAsync(new ArraySegment<byte>(buffer), timeout.Token);
            if (result.MessageType == WebSocketMessageType.Close
                || Encoding.UTF8.GetString(buffer, 0, result.Count).Contains("\"type\":7", StringComparison.Ordinal)) break;
        }
        if (socket.State is WebSocketState.Open or WebSocketState.CloseReceived)
            await socket.CloseOutputAsync(WebSocketCloseStatus.NormalClosure, "test complete", timeout.Token);
        var admission = app.Services.GetRequiredService<SignalRAdmissionControl>();
        while (admission.ActiveHubConnectionCount != 0) await Task.Delay(10, timeout.Token);
        await app.StopAsync(timeout.Token);
    }

    internal static string Generate(Guid owner) => new JwtTokenService(
        Options.Create(Settings), NullLogger<JwtTokenService>.Instance).GenerateAccessToken(new User
        {
            Id = owner, UserName = "isolated-user", Email = "isolated@example.invalid", PasswordHash = "unused",
        });

    internal static string Legacy(Guid owner, string userClaim) => new JwtSecurityTokenHandler().WriteToken(
        new JwtSecurityToken(Settings.Issuer, Settings.Audience,
            [new Claim(userClaim, owner.ToString("D")), new Claim("jti", Guid.NewGuid().ToString("D"))],
            expires: DateTime.UtcNow.AddMinutes(5),
            signingCredentials: new SigningCredentials(new SymmetricSecurityKey(Encoding.UTF8.GetBytes(SigningKey)),
                SecurityAlgorithms.HmacSha256)));

    internal static WebApplication BuildApi(MutableTokenBlacklist blacklist)
    {
        var builder = WebApplication.CreateBuilder();
        builder.WebHost.UseTestServer();
        builder.Services.AddSingleton<ITokenBlacklistService>(blacklist);
        builder.Services.AddJwtAuthentication(Configuration());
        var app = builder.Build();
        app.UseAuthentication();
        app.UseAuthorization();
        app.MapGet("/protected", () => Results.Ok()).RequireAuthorization();
        return app;
    }

    internal static IConfiguration Configuration() => new ConfigurationBuilder().AddInMemoryCollection(
        new Dictionary<string, string?>
        {
            ["JwtSettings:Secret"] = SigningKey,
            ["JwtSettings:Issuer"] = Settings.Issuer,
            ["JwtSettings:Audience"] = Settings.Audience,
        }).Build();

    private static async Task<HttpStatusCode> Status(HttpClient client, string token)
    {
        using var request = new HttpRequestMessage(HttpMethod.Get, "/protected");
        request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", token);
        using var response = await client.SendAsync(request);
        return response.StatusCode;
    }
}

internal sealed class MutableTokenBlacklist : ITokenBlacklistService
{
    private readonly HashSet<string> revoked = [];
    private readonly Dictionary<Guid, DateTime> cutoffs = [];
    public Task BlacklistTokenAsync(string jti, TimeSpan remainingLifetime, CancellationToken ct = default)
    {
        revoked.Add(jti);
        return Task.CompletedTask;
    }
    public Task InvalidateAllUserTokensAsync(Guid userId, CancellationToken ct = default)
    {
        cutoffs[userId] = DateTime.UtcNow;
        return Task.CompletedTask;
    }
    public Task<bool> IsTokenBlacklistedAsync(string jti, CancellationToken ct = default) =>
        Task.FromResult(revoked.Contains(jti));
    public Task<bool> AreUserTokensInvalidatedAsync(Guid userId, DateTime tokenIssuedAt, CancellationToken ct = default) =>
        Task.FromResult(cutoffs.TryGetValue(userId, out var cutoff) && tokenIssuedAt < cutoff);
}
