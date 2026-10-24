using System.Collections.Concurrent;
using System.Net;
using BlogApp.Presentation.Api.Extensions;
using BlogApp.Presentation.Api.Middlewares;
using BlogApp.Presentation.Api.Security;
using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.TestHost;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Xunit;

namespace BlogApp.Presentation.Api.Tests.Security;

public sealed class SignalRAdmissionTests
{
    [Fact]
    public async Task ConcurrentHttpTransportAdmissionsCannotExceedTheLastSlots()
    {
        var release = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var builder = WebApplication.CreateBuilder();
        builder.WebHost.UseTestServer();
        builder.Services.AddAgentSignalRAdmission(new ConfigurationBuilder().AddInMemoryCollection(
            new Dictionary<string, string?> { ["SignalRRateLimit:MaxConnectionsPerIp"] = "2" }).Build());
        await using var app = builder.Build();
        app.UseMiddleware<SignalRConnectionLimitMiddleware>();
        app.Run(async context => { await release.Task.WaitAsync(context.RequestAborted); context.Response.StatusCode = 200; });
        await app.StartAsync();
        var requests = Enumerable.Range(0, 32).Select(_ => app.GetTestServer().SendAsync(context =>
        {
            context.Request.Path = "/hubs/admission";
            context.Connection.RemoteIpAddress = IPAddress.Parse("203.0.113.88");
        })).ToArray();
        try
        {
            using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(10));
            while (requests.Count(task => task.IsCompleted) < 30) await Task.Delay(10, timeout.Token);
            Assert.Equal(30, requests.Count(task => task.IsCompletedSuccessfully));
            Assert.All(requests.Where(task => task.IsCompletedSuccessfully), task => Assert.Equal(429, task.Result.Response.StatusCode));
            Assert.Equal(2, app.Services.GetRequiredService<SignalRAdmissionControl>().ActiveConnectionCount);
        }
        finally { release.TrySetResult(); }
        var responses = await Task.WhenAll(requests);
        Assert.Equal(2, responses.Count(response => response.Response.StatusCode == 200));
        Assert.Equal(0, app.Services.GetRequiredService<SignalRAdmissionControl>().ActiveConnectionCount);
    }

    [Fact]
    public void GlobalConnectionCapAndIdempotentLeaseReleaseAreEnforced()
    {
        var admission = new SignalRAdmissionControl(TimeProvider.System);
        var options = new SignalRRateLimitOptions { MaxConnectionsPerIp = 2, MaxConnectionsTotal = 3 };
        Assert.True(admission.TryAcquireConnection("ip-a", options, out var first));
        Assert.True(admission.TryAcquireConnection("ip-a", options, out var second));
        Assert.False(admission.TryAcquireConnection("ip-a", options, out _));
        Assert.True(admission.TryAcquireConnection("ip-b", options, out var third));
        Assert.False(admission.TryAcquireConnection("ip-c", options, out _));
        first!.Dispose(); first.Dispose();
        Assert.Equal(2, admission.ActiveConnectionCount);
        Assert.True(admission.TryAcquireConnection("ip-c", options, out var replacement));
        second!.Dispose(); third!.Dispose(); replacement!.Dispose();
        Assert.Equal(0, admission.ActiveConnectionCount);
    }

    [Fact]
    public void LogicalHubLeasesSurviveBetweenTransportRequestsWithoutDoubleCounting()
    {
        var admission = new SignalRAdmissionControl(TimeProvider.System);
        var options = new SignalRRateLimitOptions { MaxConnectionsPerIp = 1 };
        Assert.True(admission.TryAcquireConnection("ip", options, out var poll));
        Assert.True(admission.TryAcquireHubConnection("ip", options, out var logical));
        poll!.Dispose();
        Assert.Equal(0, admission.ActiveConnectionCount);
        Assert.Equal(1, admission.ActiveHubConnectionCount);
        Assert.False(admission.TryAcquireHubConnection("ip", options, out _));
        Assert.True(admission.TryAcquireConnection("ip", options, out var nextPoll));
        nextPoll!.Dispose(); logical!.Dispose(); logical.Dispose();
        Assert.Equal(0, admission.ActiveHubConnectionCount);
        Assert.True(admission.TryAcquireHubConnection("ip", options, out var replacement));
        replacement!.Dispose();
    }

    [Fact]
    public void InvocationQuotasBindConnectionOwnerAndIpAcrossReconnects()
    {
        var clock = new ManualClock();
        var admission = new SignalRAdmissionControl(clock);
        var options = new SignalRRateLimitOptions { MaxInvocationsPerMinute = 2 };
        Assert.True(admission.TryConsumeInvocation("a", "owner", "ip", options));
        Assert.True(admission.TryConsumeInvocation("b", "owner", "ip", options));
        Assert.False(admission.TryConsumeInvocation("c", "owner", "different-ip", options));
        Assert.False(admission.TryConsumeInvocation("c", "different-owner", "ip", options));
        Assert.True(admission.TryConsumeInvocation("new", "new-owner", "new-ip", options));
        Assert.True(admission.TryConsumeInvocation("a", "new-owner", "new-ip", options));
        Assert.False(admission.TryConsumeInvocation("a", "other-owner", "other-ip", options));
        clock.Advance(TimeSpan.FromMinutes(1));
        Assert.True(admission.TryConsumeInvocation("c", "owner", "ip", options));
    }

    [Fact]
    public void InvocationStateHasAHardBoundAndExpiresWithoutAnUnboundedTimerCache()
    {
        var clock = new ManualClock();
        var admission = new SignalRAdmissionControl(clock);
        var options = new SignalRRateLimitOptions { MaxTrackedSubjects = 3 };
        Assert.True(admission.TryConsumeInvocation("a", "owner-a", "ip-a", options));
        for (var index = 0; index < 100; index++)
            Assert.False(admission.TryConsumeInvocation("b" + index, "other" + index, "ip" + index, options));
        Assert.Equal(3, admission.TrackedInvocationSubjectCount);
        admission.ForgetConnection("a");
        Assert.Equal(2, admission.TrackedInvocationSubjectCount);
        clock.Advance(TimeSpan.FromMinutes(1));
        Assert.True(admission.TryConsumeInvocation("b", "owner-b", "ip-b", options));
        Assert.Equal(3, admission.TrackedInvocationSubjectCount);
    }

    private sealed class ManualClock : TimeProvider
    {
        private long _ticks;
        public override long TimestampFrequency => TimeSpan.TicksPerSecond;
        public override long GetTimestamp() => _ticks;
        public void Advance(TimeSpan elapsed) => _ticks += elapsed.Ticks;
    }
}
