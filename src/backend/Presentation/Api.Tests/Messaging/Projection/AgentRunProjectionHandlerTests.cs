using System.Data;
using BlogApp.Core.Application.Common.Interfaces.Data;
using BlogApp.Core.Application.Common.Interfaces.Persistence;
using BlogApp.Core.Application.Common.Messaging;
using BlogApp.Core.Domain.Enums;
using BlogApp.Infrastructure.Persistence;
using BlogApp.Infrastructure.Persistence.Repositories;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using Xunit;

namespace BlogApp.Presentation.Api.Tests.Messaging.Projection;

/// <summary>
/// Projection işleyicisinin broker'sız DB davranışı: doğrulanmış olay girdisiyle
/// quarantine/applied yolları doğrudan çağrılır (broker taşıma testleri consumer
/// testlerindedir).
/// </summary>
[Collection("agent-event-projection")]
public sealed class AgentRunProjectionHandlerTests
{
    private readonly AgentEventProjectionFixture _fixture;

    public AgentRunProjectionHandlerTests(AgentEventProjectionFixture fixture)
    {
        _fixture = fixture;
    }

    [Fact]
    public async Task UnknownRun_IsQuarantined_WithoutThrowing()
    {
        await _fixture.ResetAsync();
        var unknownRunId = Guid.NewGuid();

        await using var context = _fixture.CreateContext();
        await using var unitOfWork = new UnitOfWork(context);
        var handler = new AgentRunEventProjectionHandler(
            unitOfWork, context, new BlogApp.Infrastructure.Messaging.EfAgentCollaborationStore(context),
            new BlogApp.Core.Application.Features.AgentFeature.Services.AgentResultPresentationGuard(context),
            TestNullLogger());

        var result = await handler.ApplyAsync(ProgressedEvent(unknownRunId, sequence: 1));

        Assert.True(result.RunUnknown);
        Assert.Equal("quarantined", result.InboxStatus);
        Assert.Null(result.Notification);

        var inboxRow = await context.AgentEventInboxes.AsNoTracking().SingleAsync();
        Assert.Equal(unknownRunId, inboxRow.RunId);
        Assert.False(await context.AgentRuns.AsNoTracking().AnyAsync(r => r.Id == unknownRunId));
    }

    [Fact]
    public async Task AppliedEvent_UpdatesProjection_AndWritesInbox()
    {
        await _fixture.ResetAsync();
        await using var seedContext = _fixture.CreateContext();
        var run = await AgentRunSeeder.SeedAsync(seedContext);

        await using var context = _fixture.CreateContext();
        await using var unitOfWork = new UnitOfWork(context);
        var handler = new AgentRunEventProjectionHandler(
            unitOfWork, context, new BlogApp.Infrastructure.Messaging.EfAgentCollaborationStore(context),
            new BlogApp.Core.Application.Features.AgentFeature.Services.AgentResultPresentationGuard(context),
            TestNullLogger());

        var result = await handler.ApplyAsync(CompletedEvent(run.Id, sequence: 2));

        Assert.Equal(AgentEventDecision.Apply, result.Decision);
        Assert.NotNull(result.Notification);
        Assert.Equal("Completed", result.Notification!.Status);

        var projected = await context.AgentRuns.AsNoTracking().SingleAsync(r => r.Id == run.Id);
        Assert.Equal(AgentRunStatus.Completed, projected.Status);
        Assert.Equal(2, projected.LastEventSequence);
        Assert.Equal("applied", (await context.AgentEventInboxes.AsNoTracking().SingleAsync()).Status);
    }

    /// <summary>Agent live-steps replay türetme kaynağı (ADDITIVE): UYGULANAN her
    /// olay inbox satırına PayloadJson + (progressed ise) ProgressMessage yazar;
    /// türetme bu sütunlardan yapılır. Terminal olayın snapshot'ı da saklanır.</summary>
    [Fact]
    public async Task AppliedEvent_PersistsPayloadJsonAndProgressMessage_InInbox()
    {
        await _fixture.ResetAsync();
        await using var seedContext = _fixture.CreateContext();
        var run = await AgentRunSeeder.SeedAsync(seedContext);

        await using var context = _fixture.CreateContext();
        await using var unitOfWork = new UnitOfWork(context);
        var handler = new AgentRunEventProjectionHandler(
            unitOfWork, context, new BlogApp.Infrastructure.Messaging.EfAgentCollaborationStore(context),
            new BlogApp.Core.Application.Features.AgentFeature.Services.AgentResultPresentationGuard(context),
            TestNullLogger());

        var progressed = ProgressedEvent(run.Id, sequence: 1);
        Assert.Equal(AgentEventDecision.Apply, (await handler.ApplyAsync(progressed)).Decision);
        var terminal = CompletedEvent(run.Id, sequence: 2);
        Assert.Equal(AgentEventDecision.Apply, (await handler.ApplyAsync(terminal)).Decision);

        var rows = await context.AgentEventInboxes.AsNoTracking()
            .OrderBy(i => i.EventSequence)
            .ToListAsync();
        Assert.Equal(2, rows.Count);

        Assert.Equal("applied", rows[0].Status);
        Assert.Equal(progressed.PayloadJson, rows[0].PayloadJson);
        Assert.Equal("broker'sız test olayı", rows[0].ProgressMessage);

        Assert.Equal("applied", rows[1].Status);
        Assert.Equal(terminal.PayloadJson, rows[1].PayloadJson); // terminal snapshot'ı da saklanır
        Assert.Null(rows[1].ProgressMessage); // progressed dışı olayda message taşınmaz
    }

    private static AgentRunEventProjectionEvent ProgressedEvent(Guid runId, long sequence) =>
        EnvelopeEvent("agent.run.progressed", runId, new Dictionary<string, object?>
        {
            ["event_sequence"] = sequence,
            ["kind"] = "run_started",
            ["message"] = "broker'sız test olayı",
        },
        // Gerçek consumer eşlemesi (AgentEventProjectionConsumer): progressed
        // olayında payload message alanı ProgressMessage'a taşınır — projection
        // handler bu alanı inbox satırına kalıcı yazar.
        progressMessage: "broker'sız test olayı");

    private static AgentRunEventProjectionEvent CompletedEvent(Guid runId, long sequence) =>
        EnvelopeEvent("agent.run.completed", runId, new Dictionary<string, object?>
        {
            ["event_sequence"] = sequence,
            ["selected_mode"] = "fast",
            ["answer"] = "handler test yanıtı",
            ["source_scope"] = "article",
            ["usage"] = new Dictionary<string, object?>
            {
                ["run_id"] = runId.ToString("D"),
                ["recorded_at"] = "2026-10-12T10:00:00Z",
            },
        });

    private static AgentRunEventProjectionEvent EnvelopeEvent(
        string messageType,
        Guid runId,
        Dictionary<string, object?> payload,
        string? progressMessage = null) =>
        new(
            AgentRunEventProjectionHandler.ConsumerName,
            new AgentEnvelope
            {
                MessageId = Guid.NewGuid().ToString("D"),
                MessageType = messageType,
                SchemaVersion = 1,
                RunId = runId.ToString("D"),
                ConversationId = Guid.NewGuid().ToString("D"),
                CorrelationId = Guid.NewGuid().ToString("D"),
                OccurredAt = "2026-10-12T10:00:00Z",
                Producer = "agent-py",
                Payload = System.Text.Json.JsonSerializer.SerializeToElement(payload)!,
            },
            PayloadJson: System.Text.Json.JsonSerializer.Serialize(payload),
            EventSequence: Convert.ToInt64(payload["event_sequence"]!),
            IsTerminal: messageType.EndsWith("completed") || messageType.EndsWith("failed") || messageType.EndsWith("cancelled"),
            TerminalStatus: messageType == "agent.run.completed" ? AgentRunStatus.Completed : null,
            ProgressMessage: progressMessage);

    private static Microsoft.Extensions.Logging.ILogger<AgentRunEventProjectionHandler> TestNullLogger() =>
        Microsoft.Extensions.Logging.Abstractions.NullLogger<AgentRunEventProjectionHandler>.Instance;
}
