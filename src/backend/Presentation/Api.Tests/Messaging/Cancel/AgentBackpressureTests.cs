using System.Text.Json;
using BlogApp.Core.Application.Common.Interfaces.Services;
using BlogApp.Core.Application.Common.Messaging;
using BlogApp.Core.Application.Common.Options;
using BlogApp.Core.Application.Features.AgentFeature.Commands.AcceptAgentRunCommand;
using BlogApp.Core.Application.Features.AgentFeature.Services;
using BlogApp.Core.Domain.Entities;
using BlogApp.Core.Domain.Enums;
using BlogApp.Infrastructure.Messaging;
using BlogApp.Infrastructure.Persistence;
using BlogApp.Infrastructure.Persistence.Repositories;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging.Abstractions;
using Microsoft.Extensions.Options;
using Xunit;

namespace BlogApp.Presentation.Api.Tests.Messaging.Cancel;

/// <summary>
/// B7 backpressure ve terminal yarışı senaryoları (plan satır 422-423, 433):
/// sistem düzeyi kapasite sınırı, deadline reaper ve geç terminal olayının
/// projection'ı geriye götürmemesi.
/// </summary>
[Collection("agent-b7-control")]
public class AgentBackpressureTests : IAsyncLifetime
{
    private readonly AgentControlDatabaseFixture _fixture;

    public AgentBackpressureTests(AgentControlDatabaseFixture fixture)
    {
        _fixture = fixture;
    }

    public Task InitializeAsync() => _fixture.ResetAsync();

    public Task DisposeAsync() => Task.CompletedTask;

    private AcceptAgentRunCommandHandler CreateAcceptHandler(int maxTotal, int maxPerOwner = 10)
    {
        var context = _fixture.CreateContext();
        return new AcceptAgentRunCommandHandler(
            new UnitOfWork(context),
            context,
            new TestCurrentUser(Guid.NewGuid()),
            new EfOutboxWriter(context),
            Options.Create(new AgentAcceptanceSettings { MaxActiveRunsTotal = maxTotal, MaxActiveRunsPerOwner = maxPerOwner }),
            Options.Create(new AgentMessagingSettings()),
            NullLogger<AcceptAgentRunCommandHandler>.Instance);
    }

    private static AcceptAgentRunCommandRequest ValidAcceptRequest(string key) =>
        new()
        {
            Question = "B7 kapasite testi sorusu",
            Language = "tr",
            ModePreference = "auto",
            BudgetProfile = "standard",
            ArticleId = null,
            IdempotencyKey = key,
        };

    private async Task SeedActiveRunsAsync(int count, string ownerPrefix = "u:b7-cap")
    {
        await using var context = _fixture.CreateContext();
        for (var i = 0; i < count; i++)
        {
            context.AgentRuns.Add(new AgentRun
            {
                Id = Guid.NewGuid(),
                ConversationId = Guid.NewGuid(),
                TurnSequence = 1,
                OwnerKey = $"{ownerPrefix}-{i}", // HER owner kendi kotasında: sistem sınırı bağımsız test edilir
                IdempotencyKey = $"idem-{Guid.NewGuid():N}",
                IdempotencyPayloadHash = new string('a', 64),
                Status = AgentRunStatus.Accepted,
                Question = "sistem kotası dolu testi",
                Language = "tr",
                ModePreference = "auto",
                BudgetProfile = "default",
                ContextSnapshotReference = "agent-run/x/turn/1",
                ContextSnapshotJson = "{}",
                DeadlineAt = DateTime.UtcNow.AddMinutes(10),
                AcceptedAt = DateTime.UtcNow,
            });
        }
        await context.SaveChangesAsync();
    }

    // ------------------------------------------------- sistem düzeyi kapasite sınırı

    [Fact]
    public async Task Accept_WhenSystemCapacityFull_IsRejected()
    {
        await SeedActiveRunsAsync(count: 5);
        var handler = CreateAcceptHandler(maxTotal: 5);

        var result = await handler.Handle(ValidAcceptRequest("yeni-is"), CancellationToken.None);

        Assert.True(result.IsFailure);
        Assert.Equal(BlogApp.Core.Application.Common.Errors.ErrorCategory.Domain, result.ErrorDetail!.Category);
        Assert.Contains("Sistem agent kapasitesi", result.ErrorDetail!.Message);
    }

    [Fact]
    public async Task Accept_WhenBelowSystemCapacity_IsAccepted()
    {
        await SeedActiveRunsAsync(count: 2);
        var handler = CreateAcceptHandler(maxTotal: 5);

        var result = await handler.Handle(ValidAcceptRequest("yeni-is"), CancellationToken.None);

        Assert.True(result.IsSuccess);
        Assert.False(result.Value!.Replay);
    }

    // ------------------------------------------------------------------ deadline reaper

    [Fact]
    public async Task Reaper_ClosesExpiredAcceptedRun_AndKeepsLiveRun()
    {
        await using var context = _fixture.CreateContext();
        var expired = await SeedRunAsync(context, deadlineAt: DateTime.UtcNow.AddMinutes(-5));
        var live = await SeedRunAsync(context, deadlineAt: DateTime.UtcNow.AddMinutes(5));
        int closed;
        await using (var reaperContext = _fixture.CreateContext())
        {
            var reaper = new AgentRunDeadlineReaper(reaperContext, NullLogger<AgentRunDeadlineReaper>.Instance);
            closed = await reaper.ReapExpiredAsync();
        }

        Assert.Equal(1, closed);
        await using var verify = _fixture.CreateContext();
        var expiredAfter = await verify.AgentRuns.AsNoTracking().SingleAsync(r => r.Id == expired.Id);
        Assert.Equal(AgentRunStatus.Failed, expiredAfter.Status); // süresi geçen iş kapatıldı
        Assert.NotNull(expiredAfter.TerminalAt);
        Assert.Contains("deadline_exceeded", expiredAfter.ResultJson);

        var liveAfter = await verify.AgentRuns.AsNoTracking().SingleAsync(r => r.Id == live.Id);
        Assert.Equal(AgentRunStatus.Accepted, liveAfter.Status); // canlı işe dokunulmaz
    }

    [Fact]
    public async Task Reaper_IgnoresTerminalRuns()
    {
        await using var context = _fixture.CreateContext();
        var terminal = await SeedRunAsync(context, deadlineAt: DateTime.UtcNow.AddMinutes(-5));
        terminal.Status = AgentRunStatus.Completed;
        await context.SaveChangesAsync();

        int closed;
        await using (var reaperContext = _fixture.CreateContext())
        {
            var reaper = new AgentRunDeadlineReaper(reaperContext, NullLogger<AgentRunDeadlineReaper>.Instance);
            closed = await reaper.ReapExpiredAsync();
        }

        Assert.Equal(0, closed);
    }

    // --------------------------------------------- geç terminal olayı projection'ı

    [Fact]
    public async Task LateCompletedEvent_AfterCancelled_DoesNotRestoreRun()
    {
        // Plan satır 433: "Terminal cancelled durumundan sonra gelen eski completed
        // olayını backend projection'ına uygulama. Olay teslim sırasını gerçekleşme
        // sırası yerine koyma." cancelled (seq 1) önce commit edildi; GEÇ completed
        // olayı (seq 1 ve altı) projection'ı geriye götüremez.
        await using var context = _fixture.CreateContext();
        var run = await SeedRunAsync(context, deadlineAt: DateTime.UtcNow.AddMinutes(5));

        await using (var scope = _fixture.CreateContext())
        {
            var handler = new AgentRunEventProjectionHandler(
                new UnitOfWork(scope), scope, NullLogger<AgentRunEventProjectionHandler>.Instance);
            var cancelled = await handler.ApplyAsync(CancelledEvent(run.Id, sequence: 1));
            Assert.Equal(AgentEventDecision.Apply, cancelled.Decision);
        }

        await using (var scope = _fixture.CreateContext())
        {
            var handler = new AgentRunEventProjectionHandler(
                new UnitOfWork(scope), scope, NullLogger<AgentRunEventProjectionHandler>.Instance);
            var lateCompletedSameSequence = await handler.ApplyAsync(CompletedEvent(run.Id, sequence: 1));
            var lateCompletedOlder = await handler.ApplyAsync(CompletedEvent(run.Id, sequence: 0));

            Assert.Equal(AgentEventDecision.Stale, lateCompletedSameSequence.Decision);
            Assert.Equal(AgentEventDecision.Stale, lateCompletedOlder.Decision);
        }

        await using var verify = _fixture.CreateContext();
        var projected = await verify.AgentRuns.AsNoTracking().SingleAsync(r => r.Id == run.Id);
        Assert.Equal(AgentRunStatus.Cancelled, projected.Status); // cancelled kazanır
        Assert.DoesNotContain("geç gelen yanıt", projected.ResultJson); // completed snapshot'ı YAZILMADI
    }

    private static async Task<AgentRun> SeedRunAsync(AppDbContext context, DateTime deadlineAt)
    {
        var run = new AgentRun
        {
            Id = Guid.NewGuid(),
            ConversationId = Guid.NewGuid(),
            TurnSequence = 1,
            OwnerKey = "u:b7-reaper",
            IdempotencyKey = $"idem-{Guid.NewGuid():N}",
            IdempotencyPayloadHash = new string('b', 64),
            Status = AgentRunStatus.Accepted,
            Question = "reaper testi",
            Language = "tr",
            ModePreference = "auto",
            BudgetProfile = "default",
            ContextSnapshotReference = "agent-run/x/turn/1",
            ContextSnapshotJson = "{}",
            DeadlineAt = deadlineAt,
            AcceptedAt = DateTime.UtcNow,
        };
        context.AgentRuns.Add(run);
        await context.SaveChangesAsync();
        return run;
    }

    private static AgentRunEventProjectionEvent CancelledEvent(Guid runId, long sequence) =>
        EnvelopeEvent("agent.run.cancelled", runId, new Dictionary<string, object?>
        {
            ["event_sequence"] = sequence,
            ["reason"] = "kullanıcı isteği",
        });

    private static AgentRunEventProjectionEvent CompletedEvent(Guid runId, long sequence) =>
        EnvelopeEvent("agent.run.completed", runId, new Dictionary<string, object?>
        {
            ["event_sequence"] = sequence,
            ["selected_mode"] = "fast",
            ["answer"] = "geç gelen yanıt",
            ["source_scope"] = "article",
            ["usage"] = new Dictionary<string, object?>
            {
                ["run_id"] = runId.ToString("D"),
                ["recorded_at"] = "2026-10-12T10:00:00Z",
            },
        });

    private static AgentRunEventProjectionEvent EnvelopeEvent(
        string messageType, Guid runId, Dictionary<string, object?> payload) =>
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
                Payload = JsonSerializer.SerializeToElement(payload)!,
            },
            PayloadJson: JsonSerializer.Serialize(payload),
            EventSequence: Convert.ToInt64(payload["event_sequence"]!),
            IsTerminal: messageType.EndsWith("completed") || messageType.EndsWith("failed") || messageType.EndsWith("cancelled"),
            TerminalStatus: messageType == "agent.run.cancelled"
                ? AgentRunStatus.Cancelled
                : messageType == "agent.run.completed" ? AgentRunStatus.Completed : null);

    private sealed class TestCurrentUser(Guid userId) : ICurrentUserService
    {
        public Guid? UserId => userId;
        public string? UserName => null;
        public string? Email => null;
        public string? CorrelationId => null;
        public bool IsAuthenticated => true;
        public bool IsInRole(string role) => false;
    }
}
