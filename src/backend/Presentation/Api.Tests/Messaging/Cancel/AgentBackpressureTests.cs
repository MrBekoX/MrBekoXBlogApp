using System.Text.Json;
using BlogApp.Core.Application.Common.Interfaces.Services;
using BlogApp.Core.Application.Common.Messaging;
using BlogApp.Core.Application.Common.Options;
using BlogApp.Core.Application.Features.AgentFeature.Commands.AcceptAgentRunCommand;
using BlogApp.Core.Application.Features.AgentFeature.Collaboration;
using BlogApp.Core.Application.Features.AgentFeature.Services;
using BlogApp.Core.Domain.Entities;
using BlogApp.Core.Domain.Enums;
using BlogApp.Infrastructure.Messaging;
using BlogApp.Infrastructure.Persistence;
using BlogApp.Infrastructure.Persistence.Repositories;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging.Abstractions;
using Microsoft.Extensions.Options;
using Microsoft.EntityFrameworkCore.Diagnostics;
using System.Data.Common;
using BlogApp.Core.Application.Common.Interfaces.Data;
using Microsoft.Extensions.DependencyInjection;
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

    [Theory]
    [InlineData(true)]
    [InlineData(false)]
    public async Task ConcurrentAdmission_ReservesOnlyOneRemainingSlot(bool sameOwner)
    {
        var owner = Guid.NewGuid();
        var start = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var tasks = Enumerable.Range(0, 12).Select(async index =>
        {
            await using var context = _fixture.CreateContext();
            var handler = new AcceptAgentRunCommandHandler(
                new UnitOfWork(context), context,
                new TestCurrentUser(sameOwner ? owner : Guid.NewGuid()),
                new EfOutboxWriter(context),
                Options.Create(new AgentAcceptanceSettings
                {
                    MaxActiveRunsPerOwner = sameOwner ? 1 : 10,
                    MaxActiveRunsTotal = sameOwner ? 100 : 1,
                }), Options.Create(new AgentMessagingSettings()),
                NullLogger<AcceptAgentRunCommandHandler>.Instance);
            await start.Task;
            return await handler.Handle(ValidAcceptRequest($"parallel-{index}"), CancellationToken.None);
        }).ToArray();
        start.SetResult();
        var results = await Task.WhenAll(tasks);

        Assert.Single(results, result => result.IsSuccess);
        await using var verify = _fixture.CreateContext();
        Assert.Equal(1, await verify.AgentRuns.CountAsync());
        Assert.Equal(1, await verify.OutboxMessages.CountAsync());
    }

    [Fact]
    public async Task HostedRecovery_ClosesExpiredRunWithoutWorkerEvents()
    {
        await using var seed = _fixture.CreateContext();
        var run = await SeedRunAsync(seed, DateTime.UtcNow.AddMinutes(-1));
        var services = new ServiceCollection();
        services.AddLogging();
        services.AddScoped<IApplicationDbContext>(_ => _fixture.CreateContext());
        services.AddScoped<AgentRunDeadlineReaper>();
        await using var provider = services.BuildServiceProvider();
        using var hosted = new AgentRunDeadlineService(
            provider.GetRequiredService<IServiceScopeFactory>(),
            Options.Create(new AgentAcceptanceSettings()),
            NullLogger<AgentRunDeadlineService>.Instance);
        await hosted.StartAsync(CancellationToken.None);
        try
        {
            using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(10));
            while (true)
            {
                await using var verify = _fixture.CreateContext();
                if (await verify.AgentRuns.AsNoTracking().AnyAsync(r => r.Id == run.Id && r.Status == AgentRunStatus.Failed, timeout.Token))
                    break;
                await Task.Delay(25, timeout.Token);
            }
        }
        finally
        {
            await hosted.StopAsync(CancellationToken.None);
        }
    }

    [Fact]
    public async Task Reaper_DoesNotOverwriteTerminalCommittedAfterCandidateSelection()
    {
        await using var seed = _fixture.CreateContext();
        var run = await SeedRunAsync(seed, DateTime.UtcNow.AddMinutes(-1));
        var pause = new PauseCandidateRead();
        await using var reaperContext = new AppDbContext(new DbContextOptionsBuilder<AppDbContext>()
            .UseNpgsql(_fixture.TestConnectionString).AddInterceptors(pause).Options);
        var reap = new AgentRunDeadlineReaper(reaperContext, NullLogger<AgentRunDeadlineReaper>.Instance)
            .ReapExpiredAsync();
        try
        {
            await pause.Selected.Task.WaitAsync(TimeSpan.FromSeconds(10));
            await using var terminal = _fixture.CreateContext();
            await terminal.AgentRuns.Where(r => r.Id == run.Id).ExecuteUpdateAsync(update => update
                .SetProperty(r => r.Status, AgentRunStatus.Completed)
                .SetProperty(r => r.ResultJson, "{\"answer\":\"completed while recovery was selecting\"}"));
        }
        finally
        {
            pause.Continue.TrySetResult();
        }

        Assert.Equal(0, await reap);
        await using var verify = _fixture.CreateContext();
        var saved = await verify.AgentRuns.AsNoTracking().SingleAsync(r => r.Id == run.Id);
        Assert.Equal(AgentRunStatus.Completed, saved.Status);
        Assert.Contains("completed while recovery", saved.ResultJson);
    }

    private sealed class PauseCandidateRead : DbCommandInterceptor
    {
        public TaskCompletionSource Selected { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        public TaskCompletionSource Continue { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);

        public override async ValueTask<DbDataReader> ReaderExecutedAsync(
            DbCommand command, CommandExecutedEventData eventData, DbDataReader result,
            CancellationToken cancellationToken = default)
        {
            if (command.CommandText.Contains("agent-deadline-candidates", StringComparison.Ordinal))
            {
                Selected.TrySetResult();
                await Continue.Task.WaitAsync(TimeSpan.FromSeconds(10), cancellationToken);
            }
            return result;
        }
    }

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
                new UnitOfWork(scope), scope, NoOpCollaborationStore.Instance,
                new AgentResultPresentationGuard(scope),
                NullLogger<AgentRunEventProjectionHandler>.Instance);
            var cancelled = await handler.ApplyAsync(CancelledEvent(run.Id, sequence: 1));
            Assert.Equal(AgentEventDecision.Apply, cancelled.Decision);
        }

        await using (var scope = _fixture.CreateContext())
        {
            var handler = new AgentRunEventProjectionHandler(
                new UnitOfWork(scope), scope, NoOpCollaborationStore.Instance,
                new AgentResultPresentationGuard(scope),
                NullLogger<AgentRunEventProjectionHandler>.Instance);
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

    [Theory]
    [InlineData(1, AgentEventDecision.Apply)]
    [InlineData(301, AgentEventDecision.Stale)]
    public async Task ActualTerminalOnlyReplacesBackendTimeoutInsideBoundedGrace(int elapsedSeconds, AgentEventDecision expected)
    {
        Guid runId;
        await using (var context = _fixture.CreateContext())
        {
            var run = await SeedRunAsync(context, DateTime.UtcNow.AddSeconds(-elapsedSeconds));
            runId = run.Id; run.LastEventSequence = 1; await context.SaveChangesAsync();
            await new AgentRunDeadlineReaper(context, NullLogger<AgentRunDeadlineReaper>.Instance).ReapExpiredAsync();
        }
        await using var projection = _fixture.CreateContext();
        var handler = new AgentRunEventProjectionHandler(new UnitOfWork(projection), projection,
            NoOpCollaborationStore.Instance, new AgentResultPresentationGuard(projection), NullLogger<AgentRunEventProjectionHandler>.Instance);
        var result = await handler.ApplyAsync(CompletedEvent(runId, sequence: 2));
        Assert.Equal(expected, result.Decision);
        await using var verify = _fixture.CreateContext();
        var persisted = await verify.AgentRuns.SingleAsync(r => r.Id == runId);
        Assert.Equal(expected == AgentEventDecision.Apply ? AgentRunStatus.Completed : AgentRunStatus.Failed, persisted.Status);
        if (expected == AgentEventDecision.Stale)
        {
            Assert.Equal(1, persisted.LastEventSequence);
            Assert.Contains("grace expired", (await verify.AgentEventInboxes.SingleAsync(i => i.RunId == runId)).Detail);
        }
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

    /// <summary>B9 ctor eklemesine (IAgentCollaborationStore) uyum için no-op test
    /// çifti: bu testler proposal olayı taşımaz; store metotları çağrılmaz.</summary>
    private sealed class NoOpCollaborationStore : IAgentCollaborationStore
    {
        public static readonly NoOpCollaborationStore Instance = new();

        public Task<ProposalUpsertResult> UpsertProposalAsync(AgentProposalUpsert upsert, CancellationToken cancellationToken = default) =>
            Task.FromResult(new ProposalUpsertResult(ProposalUpsertOutcome.Created, 1));

        public Task<CollaborationRunState?> GetRunStateAsync(Guid runId, CancellationToken cancellationToken = default) =>
            Task.FromResult<CollaborationRunState?>(null);

        public Task<AgentProposalSnapshot?> GetCurrentProposalAsync(Guid runId, Guid proposalId, CancellationToken cancellationToken = default) =>
            Task.FromResult<AgentProposalSnapshot?>(null);

        public Task<ConfirmationTransition> ConfirmAsync(Guid proposalRowId, string contentHash, DateTimeOffset confirmedAt, CancellationToken cancellationToken = default) =>
            Task.FromResult(ConfirmationTransition.Confirmed);

        public Task<bool> MarkResumeSentAsync(Guid proposalRowId, CancellationToken cancellationToken = default) =>
            Task.FromResult(true);
    }
}
