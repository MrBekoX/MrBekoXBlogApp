using System.Text.Json;
using BlogApp.Core.Application.Common.Interfaces.Data;
using BlogApp.Core.Application.Features.AgentFeature.Commands.RecordAgentFeedbackCommand;
using BlogApp.Core.Application.Features.AgentFeature.Queries.GetAgentObservationsQuery;
using BlogApp.Core.Domain.Entities;
using BlogApp.Core.Domain.Enums;
using BlogApp.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging.Abstractions;
using Xunit;

namespace BlogApp.Presentation.Api.Tests.Agent;

/// <summary>
/// B10 yönetim gözlem sorgusu (plan admin listesi): backlog + en eski iş yaşı,
/// outbox derinlikleri + yayın gecikmesi + hata kayıtları, projection duplicate/
/// stale/quarantined sayıları, iş süreleri + iptal gecikmesi, geri bildirim özeti.
/// Hepsi mevcut tabloların okunmasıyla; agent şeması bölümü fixture DB'sinde
/// migrate edilmediği için null döner (graceful düşme davranışı da test edilir).
/// </summary>
[Collection("agent-b10")]
public class AgentObservationsQueryTests : IAsyncLifetime
{
    private readonly AgentB10DatabaseFixture _fixture;

    public AgentObservationsQueryTests(AgentB10DatabaseFixture fixture) => _fixture = fixture;

    public Task InitializeAsync() => _fixture.ResetAsync();

    public Task DisposeAsync() => Task.CompletedTask;

    private GetAgentObservationsQueryHandler CreateHandler(AppDbContext context) =>
        new(
            context,
            systemDbConnectionFactory: null, // agent şeması bu scratch DB'de yok → bölüm null
            NullLogger<GetAgentObservationsQueryHandler>.Instance);

    [Fact]
    public async Task Observations_EmptyDatabase_ReturnsZerosAndNullSections()
    {
        var result = await CreateHandler(_fixture.CreateContext()).Handle(
            new GetAgentObservationsQueryRequest { WindowHours = 24 }, CancellationToken.None);

        Assert.True(result.IsSuccess);
        Assert.Equal(0, result.Value!.Acceptance.ActiveRuns);
        Assert.Null(result.Value.Acceptance.OldestActiveRunAgeMinutes);
        Assert.Equal(0, result.Value.Outbox.Pending);
        Assert.Equal(0, result.Value.Projection.Duplicates);
        Assert.Null(result.Value.Jobs); // agent şeması yok: hata değil, bölüm null
        Assert.Equal(0, result.Value.Feedback.Total);
    }

    [Fact]
    public async Task Observations_CountsBacklogAndOutboxDepths()
    {
        var context = _fixture.CreateContext();
        await AgentB10TestHost.SeedRunAsync(context, status: AgentRunStatus.Accepted);
        await AgentB10TestHost.SeedRunAsync(context, status: AgentRunStatus.Completed,
            resultJson: """{"answer":"ok"}""", terminalAt: DateTime.UtcNow.AddSeconds(-30));

        context.OutboxMessages.Add(new OutboxMessage
        {
            MessageId = Guid.NewGuid().ToString("D"),
            MessageType = "agent.execute.requested",
            Exchange = "blog.agent.commands",
            RoutingKey = "agent.execute.requested.v1",
            EnvelopeJson = "{}",
            Status = AgentOutboxStatus.Pending,
            CreatedAt = DateTime.UtcNow.AddMinutes(-3),
        });
        context.OutboxMessages.Add(new OutboxMessage
        {
            MessageId = Guid.NewGuid().ToString("D"),
            MessageType = "agent.cancel.requested",
            Exchange = "blog.agent.commands",
            RoutingKey = "agent.cancel.requested.v1",
            EnvelopeJson = "{}",
            Status = AgentOutboxStatus.Published,
            CreatedAt = DateTime.UtcNow.AddMinutes(-2),
            PublishedAt = DateTime.UtcNow.AddMinutes(-2).AddSeconds(1),
            AttemptCount = 2,
        });
        await context.SaveChangesAsync();
        // SaveChanges interceptor'ı CreatedAt'i üzerine yazar (AppDbContext:56);
        // gözlem pencereleri için kayıt zamanlarını raw SQL ile geri tarihle
        // ("Status" dize saklanır — enum string conversion).
        await context.Database.ExecuteSqlRawAsync(
            "UPDATE outbox_messages SET \"CreatedAt\" = now() - interval '3 minutes' WHERE \"Status\" = 'Pending'");
        await context.Database.ExecuteSqlRawAsync(
            "UPDATE outbox_messages SET \"CreatedAt\" = now() - interval '2 minutes', \"PublishedAt\" = now() - interval '2 minutes' + interval '1 seconds' WHERE \"Status\" = 'Published'");

        var result = await CreateHandler(_fixture.CreateContext()).Handle(
            new GetAgentObservationsQueryRequest { WindowHours = 24 }, CancellationToken.None);

        Assert.True(result.IsSuccess);
        Assert.Equal(1, result.Value!.Acceptance.ActiveRuns);
        Assert.NotNull(result.Value.Acceptance.OldestActiveRunAgeMinutes);
        Assert.Equal(1, result.Value.Outbox.Pending);
        Assert.Equal(1, result.Value.Outbox.Published);
        // Yayın gecikmesi: ~1 sn; attempt toplamı hata sinyali verir.
        Assert.True(result.Value.Outbox.AveragePublishLatencySeconds is > 0 and < 60);
        Assert.Equal(2, result.Value.Outbox.AttemptSum);
        Assert.Equal(1, result.Value.Outbox.RecordsWithPublishErrors);
        // İş süresi: terminal run kabul→terminal ~2 dk içinde.
        Assert.NotNull(result.Value.Runs.AverageRunSeconds);
    }

    [Fact]
    public async Task Observations_CancelLatencyFromCancelOutbox()
    {
        var context = _fixture.CreateContext();
        var run = await AgentB10TestHost.SeedRunAsync(
            context,
            status: AgentRunStatus.Cancelled,
            terminalAt: DateTime.UtcNow.AddSeconds(-10));
        var cancelledAt = DateTime.UtcNow.AddMinutes(-1);
        context.OutboxMessages.Add(new OutboxMessage
        {
            MessageId = Guid.NewGuid().ToString("D"),
            MessageType = "agent.cancel.requested",
            Exchange = "blog.agent.commands",
            RoutingKey = "agent.cancel.requested.v1",
            CorrelationId = "obs",
            RunId = run.Id,
            EnvelopeJson = "{}",
            Status = AgentOutboxStatus.Published,
            CreatedAt = cancelledAt,
            PublishedAt = cancelledAt.AddSeconds(1),
        });
        await context.SaveChangesAsync();
        // CreatedAt interceptor'ı nedeniyle raw SQL ile geri tarihleme (yukarıdaki not).
        await context.Database.ExecuteSqlRawAsync(
            $"UPDATE outbox_messages SET \"CreatedAt\" = now() - interval '1 minutes' WHERE \"RunId\" = '{run.Id:D}'");

        var result = await CreateHandler(_fixture.CreateContext()).Handle(
            new GetAgentObservationsQueryRequest { WindowHours = 24 }, CancellationToken.None);

        Assert.True(result.IsSuccess);
        // İptal gecikmesi ~50 sn (kabul -2 dk, cancel -1 dk, terminal -10 sn).
        Assert.NotNull(result.Value!.Runs.AverageCancelLatencySeconds);
        Assert.True(result.Value.Runs.AverageCancelLatencySeconds is > 0 and < 120);
        Assert.Equal(1, result.Value.Runs.TerminalCounts.GetValueOrDefault("Cancelled"));
    }

    [Fact]
    public async Task Observations_ProjectionAndFeedbackSummaries()
    {
        var context = _fixture.CreateContext();
        var run = await AgentB10TestHost.SeedRunAsync(context);
        await AgentB10TestHost.SeedAppliedEventAsync(context, run.Id, 1, "agent.run.accepted");
        context.AgentEventInboxes.Add(new AgentEventInbox
        {
            ConsumerName = "backend-agent-events",
            MessageId = Guid.NewGuid(),
            MessageType = "agent.run.progressed",
            RunId = run.Id,
            EventSequence = 0,
            Status = "duplicate",
            CreatedAt = DateTime.UtcNow,
        });

        var feedback = new ProjectionAgentFeedbackStore(context);
        await feedback.WriteAsync(new AgentFeedbackRecord
        {
            RunId = run.Id,
            FeedbackKey = "obs-fb-1",
            Rating = 5,
        }, CancellationToken.None);
        await feedback.WriteAsync(new AgentFeedbackRecord
        {
            RunId = run.Id,
            FeedbackKey = "obs-fb-2",
            Rating = 3,
        }, CancellationToken.None);
        await context.SaveChangesAsync();

        var result = await CreateHandler(_fixture.CreateContext()).Handle(
            new GetAgentObservationsQueryRequest { WindowHours = 24 }, CancellationToken.None);

        Assert.True(result.IsSuccess);
        Assert.Equal(1, result.Value!.Projection.Applied);
        Assert.Equal(1, result.Value.Projection.Duplicates);
        Assert.Equal(2, result.Value.Feedback.Total);
        Assert.Equal(4.0, result.Value.Feedback.AverageRating);
        Assert.Equal(1, result.Value.Feedback.RatingCounts[5]);
        Assert.Equal(1, result.Value.Feedback.RatingCounts[3]);
    }
}
