using System.IdentityModel.Tokens.Jwt;
using System.Net.Http.Headers;
using System.Text;
using Asp.Versioning;
using BlogApp.Core.Application.Common.Interfaces.Services;
using BlogApp.Core.Application.Common.Models;
using BlogApp.Core.Application.Features.AgentFeature.Queries.GetAgentRunEventsQuery;
using BlogApp.Presentation.Api.Endpoints;
using BlogApp.Presentation.Api.Extensions;
using BlogApp.Presentation.Api.Services;
using MediatR;
using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.TestHost;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.IdentityModel.Tokens;
using Xunit;

namespace BlogApp.Presentation.Api.Tests.Security;

public sealed class AgentSseCredentialTests
{
    [Theory]
    [InlineData("jti", false)]
    [InlineData("account", false)]
    [InlineData("expiry", false)]
    [InlineData("valid", true)]
    [InlineData("guest", true)]
    public async Task StreamChecksCurrentCredentialsAfterAwaitingReplay(string scenarioName, bool mayReceiveContent)
    {
        // Real endpoint and JWT middleware, with controlled page transport.
        // Resource ownership/presentation are covered by the database suites.
        var owner = Guid.NewGuid();
        var scenario = new ReplayScenario();
        var clock = new StreamClock(DateTimeOffset.UtcNow);
        var blacklist = new MutableTokenBlacklist();
        var builder = WebApplication.CreateBuilder();
        builder.WebHost.UseTestServer();
        builder.Services.AddSingleton(scenario);
        builder.Services.AddSingleton<TimeProvider>(clock);
        builder.Services.AddSingleton<ITokenBlacklistService>(blacklist);
        builder.Services.AddJwtAuthentication(AgentCredentialLifetimeTests.Configuration());
        builder.Services.AddMediatR(configuration => configuration.RegisterServicesFromAssemblyContaining<ReplayHandler>());
        builder.Services.AddHttpContextAccessor();
        builder.Services.AddScoped<IAgentGuestSessionService, AgentGuestSessionService>();
        builder.Services.AddApiVersioning(options =>
        {
            options.DefaultApiVersion = new ApiVersion(1, 0);
            options.AssumeDefaultVersionWhenUnspecified = true;
            options.ApiVersionReader = new UrlSegmentApiVersionReader();
        });
        await using var app = builder.Build();
        app.UseAuthentication();
        app.UseAuthorization();
        app.RegisterAgentEndpoints();
        app.MapGet("/credential-check", () => Results.Ok()).RequireAuthorization();
        await app.StartAsync();
        var token = AgentCredentialLifetimeTests.Generate(owner);
        if (scenarioName == "expiry")
        {
            var claims = new JwtSecurityTokenHandler().ReadJwtToken(token).Claims.Where(claim => claim.Type != "exp");
            token = new JwtSecurityTokenHandler().WriteToken(new JwtSecurityToken(
                AgentCredentialLifetimeTests.Settings.Issuer, AgentCredentialLifetimeTests.Settings.Audience, claims,
                expires: DateTime.UtcNow.AddSeconds(1),
                signingCredentials: new SigningCredentials(new SymmetricSecurityKey(
                    Encoding.UTF8.GetBytes(AgentCredentialLifetimeTests.SigningKey)), SecurityAlgorithms.HmacSha256)));
        }
        using var client = app.GetTestClient();
        using var request = new HttpRequestMessage(HttpMethod.Get, $"/api/v1/agent/runs/{Guid.NewGuid():D}/events");
        request.Headers.Accept.ParseAdd("text/event-stream");
        if (scenarioName == "guest")
            request.Headers.Add("Cookie", AgentGuestSessionService.CookieName + "=" + Guid.NewGuid().ToString("D"));
        else
            request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", token);
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(12));
        using var response = await client.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, timeout.Token);
        response.EnsureSuccessStatusCode();
        using var reader = new StreamReader(await response.Content.ReadAsStreamAsync(timeout.Token));
        while (await reader.ReadLineAsync(timeout.Token) is { } line)
            if (line.Contains("first-public-page", StringComparison.Ordinal)) break;
        await scenario.SecondPageRequested.Task.WaitAsync(timeout.Token);
        if (scenarioName == "jti")
            await blacklist.BlacklistTokenAsync(new JwtSecurityTokenHandler().ReadJwtToken(token).Id, TimeSpan.FromMinutes(5));
        if (scenarioName == "account") await blacklist.InvalidateAllUserTokensAsync(owner);
        if (scenarioName == "expiry")
            clock.MoveTo(new DateTimeOffset(new JwtSecurityTokenHandler().ReadJwtToken(token).ValidTo).AddSeconds(1));
        scenario.ReleaseSecondPage.TrySetResult();
        var remaining = await reader.ReadToEndAsync(timeout.Token);
        if (mayReceiveContent)
        {
            Assert.Contains("private-next-page-sentinel", remaining);
            Assert.Contains("event: done", remaining);
        }
        else
        {
            Assert.DoesNotContain("private-next-page-sentinel", remaining);
            Assert.Contains("event: error", remaining);
            if (scenarioName is "jti" or "account")
            {
                using var fresh = new HttpRequestMessage(HttpMethod.Get, "/credential-check");
                fresh.Headers.Authorization = new AuthenticationHeaderValue("Bearer", token);
                using var freshResponse = await client.SendAsync(fresh, timeout.Token);
                Assert.Equal(System.Net.HttpStatusCode.Unauthorized, freshResponse.StatusCode);
            }
        }
    }

    public sealed class ReplayScenario
    {
        public int Calls;
        public TaskCompletionSource SecondPageRequested { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        public TaskCompletionSource ReleaseSecondPage { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
    }

    private sealed class StreamClock(DateTimeOffset initial) : TimeProvider
    {
        private long utcTicks = initial.UtcTicks;
        public override DateTimeOffset GetUtcNow() => new(Interlocked.Read(ref utcTicks), TimeSpan.Zero);
        public void MoveTo(DateTimeOffset value) => Interlocked.Exchange(ref utcTicks, value.UtcTicks);
    }

    public sealed class ReplayHandler(ReplayScenario scenario)
        : IRequestHandler<GetAgentRunEventsQueryRequest, Result<AgentRunEventsDto>>
    {
        public async Task<Result<AgentRunEventsDto>> Handle(GetAgentRunEventsQueryRequest request, CancellationToken cancellationToken)
        {
            var second = Interlocked.Increment(ref scenario.Calls) > 1;
            if (second)
            {
                scenario.SecondPageRequested.TrySetResult();
                await scenario.ReleaseSecondPage.Task.WaitAsync(cancellationToken);
            }
            return Result<AgentRunEventsDto>.Success(new AgentRunEventsDto
            {
                RunId = request.RunId, RunStatus = second ? "Completed" : "Running", HasMore = !second,
                LastEventSequence = second ? 2 : 1,
                Events = [new AgentRunEventDto
                {
                    EventSequence = second ? 2 : 1, MessageType = "agent.run.progressed",
                    MessageId = Guid.NewGuid().ToString("D"), OccurredAt = DateTimeOffset.UtcNow,
                    Kind = "generation_delta", Message = second ? "private-next-page-sentinel" : "first-public-page",
                }],
            });
        }
    }
}
