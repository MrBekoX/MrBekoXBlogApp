using BlogApp.BuildingBlocks.Messaging;
using BlogApp.Core.Application.Features.AgentFeature.Services;
using BlogApp.Infrastructure.Messaging;
using BlogApp.Presentation.Api.Extensions;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using OpenTelemetry;
using OpenTelemetry.Metrics;
using Xunit;

namespace BlogApp.Presentation.Api.Tests.Agent;

public sealed class AgentRecoveryConfigurationTests
{
    [Fact]
    public void AgentOutbox_RegistersScopedRecoveryAndItsHost()
    {
        var services = new ServiceCollection();
        services.AddAgentOutbox(new ConfigurationBuilder().Build());
        Assert.Contains(services, d => d.ServiceType == typeof(AgentRunDeadlineReaper)
                                      && d.Lifetime == ServiceLifetime.Scoped);
        Assert.Contains(services, d => d.ServiceType == typeof(IHostedService)
                                      && d.ImplementationType == typeof(AgentRunDeadlineService));
    }

    [Fact]
    public void OutboxMetrics_AreCollectedByConfiguredTelemetryProvider()
    {
        var services = new ServiceCollection();
        services.AddLogging();
        services.AddObservabilityServices(new ConfigurationBuilder().Build());
        var exporter = new RecordingExporter();
        using var reader = new PeriodicExportingMetricReader(exporter, exportIntervalMilliseconds: 60_000);
        services.AddOpenTelemetry().WithMetrics(metrics => metrics.AddReader(reader));
        using var servicesProvider = services.BuildServiceProvider();
        var meterProvider = servicesProvider.GetRequiredService<MeterProvider>();

        OutboxMetrics.Published.Add(1);
        // Collect the recording reader directly: the configured pull-based
        // Prometheus reader deliberately does not support ForceFlush.
        Assert.True(reader.Collect());
        Assert.Contains("outbox.published", exporter.Names);
    }

    [Fact]
    public async Task DeliveryRetry_TransientFailureSucceedsOnNextAttempt()
    {
        var attempts = 0;
        await ConsumerDeliveryRetry.ExecuteAsync(_ =>
        {
            if (++attempts == 1) throw new TimeoutException();
            return Task.CompletedTask;
        }, error => error is TimeoutException, [TimeSpan.Zero], CancellationToken.None);
        Assert.Equal(2, attempts);
    }

    [Fact]
    public async Task DeliveryRetry_PermanentFailureIsNotRetried()
    {
        var attempts = 0;
        await Assert.ThrowsAsync<ArgumentException>(() => ConsumerDeliveryRetry.ExecuteAsync(_ =>
        {
            attempts++;
            throw new ArgumentException();
        }, error => error is TimeoutException, [TimeSpan.Zero], CancellationToken.None));
        Assert.Equal(1, attempts);
    }

    [Fact]
    public async Task DeliveryRetry_StopsAfterBoundedAttempts()
    {
        var attempts = 0;
        await Assert.ThrowsAsync<TimeoutException>(() => ConsumerDeliveryRetry.ExecuteAsync(_ =>
        {
            attempts++;
            throw new TimeoutException();
        }, _ => true, [TimeSpan.Zero, TimeSpan.Zero], CancellationToken.None));
        Assert.Equal(3, attempts);
    }

    [Fact]
    public async Task DeliveryRetry_ShutdownInterruptsDelay()
    {
        using var cancellation = new CancellationTokenSource();
        var attempts = 0;
        var delivery = ConsumerDeliveryRetry.ExecuteAsync(_ =>
        {
            attempts++;
            cancellation.Cancel();
            throw new TimeoutException();
        }, _ => true, [TimeSpan.FromSeconds(120)], cancellation.Token);
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => delivery);
        Assert.Equal(1, attempts);
    }

    private sealed class RecordingExporter : BaseExporter<Metric>
    {
        public HashSet<string> Names { get; } = [];
        public override ExportResult Export(in Batch<Metric> batch)
        {
            foreach (var metric in batch) Names.Add(metric.Name);
            return ExportResult.Success;
        }
    }
}
