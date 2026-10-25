using System.Diagnostics;
using System.Net;
using System.Text;
using BlogApp.Presentation.Api.Extensions;
using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Http;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using OpenTelemetry.Trace;
using Xunit;

namespace BlogApp.Presentation.Api.Tests.Agent;

public sealed class AgentTelemetryExportTests
{
    [Theory]
    [InlineData("ftp://private-config-sentinel/v1/traces", "250")]
    [InlineData("http://private-user:private-config-sentinel@127.0.0.1/v1/traces", "250")]
    [InlineData("http://127.0.0.1/v1/traces?token=private-config-sentinel", "250")]
    [InlineData("http://127.0.0.1/v1/traces#private-config-sentinel", "250")]
    [InlineData("http://127.0.0.1/private-config-sentinel", "250")]
    [InlineData("http://127.0.0.1/v1/traces", "0")]
    [InlineData("http://127.0.0.1/v1/traces", "10001")]
    [InlineData("http://127.0.0.1/v1/traces", "private-config-sentinel")]
    public async Task ExplicitInvalidCollectorConfigurationFailsStartupWithoutEchoingItsValue(string endpoint, string timeout)
    {
        var error = await Assert.ThrowsAsync<ArgumentException>(async () =>
        {
            using var host = CreateHost(endpoint, timeout);
            await host.StartAsync();
        });
        Assert.DoesNotContain("private-", error.ToString());
    }

    [Fact]
    public async Task EmptyCollectorEndpointKeepsExportDisabledWithoutParsingUnusedOptions()
    {
        using var host = CreateHost("", "unused-private-config-sentinel");
        await host.StartAsync();
        await host.StopAsync();
    }

    [Fact]
    public async Task ConfiguredHttpCollectorReceivesTraceIdentityWithoutPrivateContent()
    {
        var received = new TaskCompletionSource<byte[]>(TaskCreationOptions.RunContinuationsAsynchronously);
        var collectorBuilder = WebApplication.CreateBuilder();
        collectorBuilder.WebHost.UseKestrel(options => options.Listen(IPAddress.Loopback, 0));
        await using var collector = collectorBuilder.Build();
        collector.MapPost("/v1/traces", async context =>
        {
            using var body = new MemoryStream();
            await context.Request.Body.CopyToAsync(body, context.RequestAborted);
            received.TrySetResult(body.ToArray());
            context.Response.ContentType = "application/x-protobuf";
        });
        await collector.StartAsync();
        var endpoint = collector.Urls.Single() + "/v1/traces";

        using var host = CreateHost(endpoint);
        await host.StartAsync();
        using var source = new ActivitySource("BlogApp");
        ActivityTraceId traceId;
        using (var activity = source.StartActivity("agent.request"))
        {
            Assert.NotNull(activity);
            traceId = activity.TraceId;
            activity.SetTag("agent.mode", "fast");
            activity.SetTag("prompt", "private-prompt-sentinel");
            activity.SetTag("url.full", "https://example.invalid/?access_token=private-token-sentinel");
            activity.SetTag("db.statement", "SELECT private-profile-sentinel");
            activity.SetStatus(ActivityStatusCode.Error, "private-exception-sentinel");
        }
        using (var unsafeEvent = source.StartActivity("agent.failure"))
        {
            Assert.NotNull(unsafeEvent);
            unsafeEvent.AddEvent(new ActivityEvent("exception", tags: new ActivityTagsCollection
            {
                ["exception.message"] = "private-event-sentinel",
            }));
        }
        host.Services.GetRequiredService<TracerProvider>().ForceFlush(5000);
        var bytes = await received.Task.WaitAsync(TimeSpan.FromSeconds(8));
        Assert.True(bytes.AsSpan().IndexOf(Convert.FromHexString(traceId.ToHexString())) >= 0,
            "The real HTTP protobuf collector did not receive the source trace identity.");
        var text = Encoding.UTF8.GetString(bytes);
        Assert.Contains("agent.mode", text);
        Assert.DoesNotContain("private-", text);
        await host.StopAsync();
    }

    [Fact]
    public async Task CollectorFailureDoesNotChangeTheApplicationOperationOrThrowDuringFlush()
    {
        // Port zero is rejected by the transport without contacting any external service.
        using var host = CreateHost("http://127.0.0.1:0/v1/traces");
        await host.StartAsync();
        using var source = new ActivitySource("BlogApp");
        string result;
        using (var activity = source.StartActivity("agent.request"))
        {
            Assert.NotNull(activity);
            result = "verified-result";
        }
        var exception = Record.Exception(() => host.Services.GetRequiredService<TracerProvider>().ForceFlush(1500));
        Assert.Null(exception);
        Assert.Equal("verified-result", result);
        await host.StopAsync();
    }

    private static IHost CreateHost(string endpoint, string timeout = "250")
    {
        var configuration = new ConfigurationBuilder().AddInMemoryCollection(new Dictionary<string, string?>
        {
            ["AgentTelemetry:Endpoint"] = endpoint,
            ["AgentTelemetry:TimeoutMilliseconds"] = timeout,
        }).Build();
        return Host.CreateDefaultBuilder()
            .ConfigureServices(services => services.AddObservabilityServices(configuration))
            .Build();
    }
}
