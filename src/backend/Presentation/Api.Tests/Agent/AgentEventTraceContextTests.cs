using System.Diagnostics;
using System.Reflection;
using System.Text.Json;
using BlogApp.BuildingBlocks.Messaging;
using BlogApp.Core.Application.Common.Messaging;
using BlogApp.Core.Application.Common.Options;
using BlogApp.Infrastructure.Messaging;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging.Abstractions;
using Microsoft.Extensions.Options;
using Xunit;

namespace BlogApp.Presentation.Api.Tests.Agent;

public sealed class AgentEventTraceContextTests
{
    [Theory]
    [InlineData("remote")]
    [InlineData("missing")]
    [InlineData("zero_ids")]
    public async Task ValidatedConsumerDeliveryRestoresItsParentBeforeProjection(string parentKind)
    {
        using var remote = new Activity("worker").SetIdFormat(ActivityIdFormat.W3C).Start();
        var parent = remote.Id;
        var traceId = remote.TraceId;
        var parentSpanId = remote.SpanId;
        remote.Stop();
        using var listener = new ActivityListener
        {
            ShouldListenTo = source => source.Name == "BlogApp",
            Sample = (ref ActivityCreationOptions<ActivityContext> _) => ActivitySamplingResult.AllDataAndRecorded,
        };
        ActivitySource.AddActivityListener(listener);
        var scopeFactory = new CaptureProjectionBoundary();
        var settings = new RabbitMqSettings();
        await using var connections = new RabbitMqConnectionManager(settings);
        await using var consumer = new AgentEventProjectionConsumer(connections, settings, scopeFactory,
            Options.Create(new AgentCollaborationSettings()), NullLogger<AgentEventProjectionConsumer>.Instance);
        var envelope = new AgentEnvelope
        {
            MessageId = Guid.NewGuid().ToString("D"), MessageType = "agent.run.progressed", SchemaVersion = 1,
            CorrelationId = Guid.NewGuid().ToString("D"), RunId = Guid.NewGuid().ToString("D"),
            ConversationId = Guid.NewGuid().ToString("D"), Producer = "agent-py",
            OccurredAt = AgentCommandEnvelopeComposer.FormatUtc(DateTimeOffset.UtcNow),
            TraceContext = parentKind switch
            {
                "remote" => parent,
                "zero_ids" => "00-00000000000000000000000000000000-0000000000000000-01",
                _ => null,
            },
            Payload = JsonSerializer.SerializeToElement(new { event_sequence = 1, kind = "retrieval_started", message = "safe" }),
        };
        var bytes = JsonSerializer.SerializeToUtf8Bytes(envelope, AgentCommandEnvelopeComposer.SerializerOptions);
        var handle = typeof(AgentEventProjectionConsumer).GetMethod("HandleAsync", BindingFlags.Instance | BindingFlags.NonPublic)!;
        // Execute production validation and projection dispatch. Stop at the DI
        // boundary so this transport/context test never opens a broker or DB.
        await Assert.ThrowsAsync<ProjectionBoundaryReachedException>(async () =>
            await (Task)handle.Invoke(consumer, ["blog.agent.events", "agent.run.progressed.v1", bytes, null, CancellationToken.None])!);
        var activity = scopeFactory.CurrentAtProjection;
        Assert.NotNull(activity);
        Assert.Equal("BlogApp", activity.Source.Name);
        Assert.Equal(ActivityKind.Consumer, activity.Kind);
        Assert.Empty(activity.Baggage);
        if (parentKind == "remote")
        {
            Assert.Equal(traceId, activity.TraceId);
            Assert.Equal(parentSpanId, activity.ParentSpanId);
        }
        else
        {
            Assert.NotEqual(default, activity.TraceId);
            Assert.Equal(default, activity.ParentSpanId);
        }
        Assert.Null(Activity.Current);
    }

    private sealed class ProjectionBoundaryReachedException : Exception;

    private sealed class CaptureProjectionBoundary : IServiceScopeFactory
    {
        public Activity? CurrentAtProjection { get; private set; }
        public IServiceScope CreateScope()
        {
            CurrentAtProjection = Activity.Current;
            throw new ProjectionBoundaryReachedException();
        }
    }
}
