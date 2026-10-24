using System.Text;
using System.Text.Json;
using BlogApp.BuildingBlocks.Messaging;
using BlogApp.Core.Application.Common.Interfaces.Data;
using BlogApp.Core.Application.Common.Interfaces.Persistence;
using BlogApp.Core.Application.Common.Messaging;
using BlogApp.Core.Domain.Enums;
using BlogApp.Infrastructure.Messaging;
using BlogApp.Infrastructure.Persistence;
using BlogApp.Infrastructure.Persistence.Repositories;
using BlogApp.Presentation.Api.Tests.Messaging.Broker;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Diagnostics;
using System.Data.Common;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging;
using RabbitMQ.Client;
using Xunit;

namespace BlogApp.Presentation.Api.Tests.Messaging.Projection;

/// <summary>
/// B5 gerçek broker + postgres projection senaryoları (GATE kabul ölçütleri):
/// duplicate, ters sıra, terminal sonrası eski progress ve bağlantı kaybı sonrası
/// replay doğru sonuç üretir. Olaylar gerçek agent_svc rolüyle blog.agent.events
/// exchange'ine yayınlanır; tüketim gerçek RabbitMqAgentConsumer tabanıyla yapılır.
/// </summary>
[Collection("agent-event-projection")]
public sealed class AgentEventProjectionConsumerTests
{
    private readonly AgentEventProjectionFixture _fixture;

    public AgentEventProjectionConsumerTests(AgentEventProjectionFixture fixture)
    {
        _fixture = fixture;
    }

    [Fact]
    public async Task RunEvents_AreProjected_Through_RealBroker()
    {
        await _fixture.ResetAsync();
        await _fixture.PurgeQueuesAsync();
        var (runId, conversationId, correlationId) = (Guid.NewGuid(), Guid.NewGuid(), Guid.NewGuid());
        await SeedRunAsync(runId);

        var notifier = new RecordingNotifier();
        await using var host = BuildHost(notifier);
        var consumer = host.GetRequiredService<AgentEventProjectionConsumer>();
        await consumer.StartAsync();
        try
        {
            await PublishAsync(conversationId, correlationId, MessageType("agent.run.mode_selected", runId, 1,
                new { event_sequence = 1, selected_mode = "deep_research", requires_web_search = true, reason = "araştırma istendi" }));
            await PublishAsync(conversationId, correlationId, MessageType("agent.run.progressed", runId, 2,
                new { event_sequence = 2, kind = "research_started", message = "araştırma turu başladı" }));
            await PublishAsync(conversationId, correlationId, MessageType("agent.run.completed", runId, 3,
                CompletedPayload(runId, 3)));

            await WaitForAsync(async () => await RunStatusAsync(runId) == AgentRunStatus.Completed);
            await WaitForAsync(() => Task.FromResult(notifier.Count >= 3));
        }
        finally
        {
            await consumer.StopAsync();
        }

        await using var context = _fixture.CreateContext();
        var run = await context.AgentRuns.AsNoTracking().SingleAsync(r => r.Id == runId);
        Assert.Equal(AgentRunStatus.Completed, run.Status);
        Assert.Equal(3, run.LastEventSequence);
        Assert.Equal("deep_research", run.SelectedMode);
        Assert.Equal("article", run.SourceScope);
        Assert.NotNull(run.ResultJson);
        Assert.NotNull(run.TerminalAt);
        Assert.Contains("answer", run.ResultJson!);

        // Tekrarlı olay yeniden uygulanmaz: her message_id için tek applied satırı.
        var appliedRows = await context.AgentEventInboxes.AsNoTracking()
            .Where(i => i.RunId == runId && i.Status == "applied")
            .CountAsync();
        Assert.Equal(3, appliedRows);

        // Commit edilmiş projection üzerinden UI bildirimi: her uygulanan olay bildirir.
        Assert.Equal(3, notifier.Count);
        var terminalNotification = notifier.Notifications.Single(n => n.MessageType == "agent.run.completed");
        Assert.Equal(runId.ToString("D"), terminalNotification.RunId);
        Assert.Equal("Completed", terminalNotification.Status);
        Assert.Equal(3, terminalNotification.EventSequence);

        Assert.Equal(0, await _fixture.QueueDepthAsync(AgentMessagingTopology.BackendEventsQueue));
    }

    [Fact]
    public async Task DuplicateDelivery_IsAppliedOnlyOnce()
    {
        await _fixture.ResetAsync();
        await _fixture.PurgeQueuesAsync();
        var (runId, conversationId, correlationId) = (Guid.NewGuid(), Guid.NewGuid(), Guid.NewGuid());
        await SeedRunAsync(runId);

        var messageId = Guid.NewGuid().ToString("D");
        var envelope = MessageType("agent.run.completed", runId, 1, CompletedPayload(runId, 1), messageId);

        var notifier = new RecordingNotifier();
        await using var host = BuildHost(notifier);
        var consumer = host.GetRequiredService<AgentEventProjectionConsumer>();
        await consumer.StartAsync();
        try
        {
            await PublishAsync(conversationId, correlationId, envelope, messageId);
            await PublishAsync(conversationId, correlationId, envelope, messageId); // tekrar teslim

            await WaitForAsync(async () => await RunStatusAsync(runId) == AgentRunStatus.Completed);
            await WaitForAsync(async () => await _fixture.QueueDepthAsync(AgentMessagingTopology.BackendEventsQueue) == 0);
            await WaitForAsync(async () =>
            {
                await using var context = _fixture.CreateContext();
                var rows = await context.AgentEventInboxes.AsNoTracking()
                    .Where(i => i.MessageId == Guid.Parse(messageId))
                    .CountAsync();
                return rows >= 1;
            });
            // İkinci teslimin kararı işlenene kadar kısa bekleme (duplicate satırı yazılmaz).
            await Task.Delay(500);
        }
        finally
        {
            await consumer.StopAsync();
        }

        await using var verify = _fixture.CreateContext();
        var inboxRows = await verify.AgentEventInboxes.AsNoTracking()
            .Where(i => i.MessageId == Guid.Parse(messageId))
            .ToListAsync();
        var run = await verify.AgentRuns.AsNoTracking().SingleAsync(r => r.Id == runId);

        Assert.Equal(AgentRunStatus.Completed, run.Status);
        Assert.Equal(1, run.LastEventSequence);
        Assert.Single(inboxRows); // PK (consumer, message_id) benzersizliği: ikinci teslim satır yazamaz

        // Duplicate kararında ikinci UI bildirimi üretilmez.
        Assert.Equal(1, notifier.Count);
    }

    [Fact]
    public async Task OutOfOrderDelivery_OldSequenceIsIgnored()
    {
        await _fixture.ResetAsync();
        await _fixture.PurgeQueuesAsync();
        var (runId, conversationId, correlationId) = (Guid.NewGuid(), Guid.NewGuid(), Guid.NewGuid());
        await SeedRunAsync(runId);

        var notifier = new RecordingNotifier();
        await using var host = BuildHost(notifier);
        var consumer = host.GetRequiredService<AgentEventProjectionConsumer>();
        await consumer.StartAsync();
        try
        {
            // Önce YENİ olay: sequence 2.
            await PublishAsync(conversationId, correlationId, MessageType("agent.run.progressed", runId, 2,
                new { event_sequence = 2, kind = "generation_started", message = "üretim başladı" }));
            await WaitForAsync(async () => await LastSequenceAsync(runId) == 2);

            // Sonra ESKİ olay: sequence 1 (ters sıra) — uygulanmaz.
            await PublishAsync(conversationId, correlationId, MessageType("agent.run.progressed", runId, 1,
                new { event_sequence = 1, kind = "retrieval_started", message = "eski olay" }));
            await WaitForAsync(async () =>
            {
                await using var context = _fixture.CreateContext();
                return await context.AgentEventInboxes.AsNoTracking()
                    .AnyAsync(i => i.RunId == runId && i.Status == "stale");
            });
        }
        finally
        {
            await consumer.StopAsync();
        }

        await using var context = _fixture.CreateContext();
        var run = await context.AgentRuns.AsNoTracking().SingleAsync(r => r.Id == runId);
        Assert.Equal(2, run.LastEventSequence); // gerileme yok
        Assert.Equal(1, notifier.Count); // eski olay bildiri üretmez
    }

    [Fact]
    public async Task OldProgress_AfterTerminal_DoesNotRegressStatus()
    {
        await _fixture.ResetAsync();
        await _fixture.PurgeQueuesAsync();
        var (runId, conversationId, correlationId) = (Guid.NewGuid(), Guid.NewGuid(), Guid.NewGuid());
        await SeedRunAsync(runId);

        var notifier = new RecordingNotifier();
        await using var host = BuildHost(notifier);
        var consumer = host.GetRequiredService<AgentEventProjectionConsumer>();
        await consumer.StartAsync();
        try
        {
            await PublishAsync(conversationId, correlationId, MessageType("agent.run.completed", runId, 5,
                CompletedPayload(runId, 5)));
            await WaitForAsync(async () => await RunStatusAsync(runId) == AgentRunStatus.Completed);

            // Terminalden SONRA gelen eski progress: durumu geri götürmez.
            await PublishAsync(conversationId, correlationId, MessageType("agent.run.progressed", runId, 4,
                new { event_sequence = 4, kind = "generation_completed", message = "geç gelen ilerleme" }));
            await WaitForAsync(async () =>
            {
                await using var context = _fixture.CreateContext();
                return await context.AgentEventInboxes.AsNoTracking()
                    .AnyAsync(i => i.RunId == runId && i.Status == "stale");
            });
        }
        finally
        {
            await consumer.StopAsync();
        }

        await using var context = _fixture.CreateContext();
        var run = await context.AgentRuns.AsNoTracking().SingleAsync(r => r.Id == runId);
        Assert.Equal(AgentRunStatus.Completed, run.Status); // terminal-öncelik: regresyon yok
        Assert.Equal(5, run.LastEventSequence);
        Assert.Equal(1, notifier.Count);
    }

    [Fact]
    public async Task ConnectionLoss_EventPublishedWhileConsumerDown_IsReplayedOnce()
    {
        await _fixture.ResetAsync();
        await _fixture.PurgeQueuesAsync();
        var (runId, conversationId, correlationId) = (Guid.NewGuid(), Guid.NewGuid(), Guid.NewGuid());
        await SeedRunAsync(runId);

        var messageId = Guid.NewGuid().ToString("D");
        // Tüketici YOKKEN yayın: mesaj kuyrukta kalıcı bekler (durable).
        await PublishAsync(conversationId, correlationId,
            MessageType("agent.run.completed", runId, 1, CompletedPayload(runId, 1), messageId), messageId);
        Assert.Equal(1, await _fixture.QueueDepthAsync(AgentMessagingTopology.BackendEventsQueue));

        // Tüketici "bağlantısı geri gelen" istemci gibi kuyruğa bağlanır: replay.
        var notifier = new RecordingNotifier();
        await using (var host = BuildHost(notifier))
        {
            var consumer = host.GetRequiredService<AgentEventProjectionConsumer>();
            await consumer.StartAsync();
            try
            {
                await WaitForAsync(async () => await RunStatusAsync(runId) == AgentRunStatus.Completed);
                await WaitForAsync(async () =>
                    await _fixture.QueueDepthAsync(AgentMessagingTopology.BackendEventsQueue) == 0);
            }
            finally
            {
                await consumer.StopAsync();
            }
        }

        // Yeniden bağlanan ikinci tüketici aynı olayı yeniden uygulamaz (ACK sonrası
        // kuyruk boş; inbox kaydı tek).
        var secondNotifier = new RecordingNotifier();
        await using (var secondHost = BuildHost(secondNotifier))
        {
            var consumer = secondHost.GetRequiredService<AgentEventProjectionConsumer>();
            await consumer.StartAsync();
            try
            {
                await Task.Delay(800); // kısa tüketim penceresi: yeniden uygulama olsaydı burada olurdu
            }
            finally
            {
                await consumer.StopAsync();
            }
        }

        await using var context = _fixture.CreateContext();
        var run = await context.AgentRuns.AsNoTracking().SingleAsync(r => r.Id == runId);
        Assert.Equal(AgentRunStatus.Completed, run.Status);
        Assert.Equal(1, run.LastEventSequence);
        var inboxRows = await context.AgentEventInboxes.AsNoTracking()
            .Where(i => i.MessageId == Guid.Parse(messageId))
            .CountAsync();
        Assert.Equal(1, inboxRows);
        Assert.Equal(0, secondNotifier.Count);
    }

    [Fact]
    public async Task UnknownRun_EventIsQuarantinedAndAcked()
    {
        await _fixture.ResetAsync();
        await _fixture.PurgeQueuesAsync();
        var unknownRunId = Guid.NewGuid();
        var (conversationId, correlationId) = (Guid.NewGuid(), Guid.NewGuid());
        var messageId = Guid.NewGuid().ToString("D");
        var logs = new MemoryLogProvider();

        await using var host = BuildHost(new RecordingNotifier(), logs);
        var consumer = host.GetRequiredService<AgentEventProjectionConsumer>();
        await consumer.StartAsync();
        try
        {
            // messageId BOTH'UN İÇİNE yazılır: projection body message_id ile çalışır
            // (AMQP property yalnız taşıma kimliğidir; handler gövdeyi esas alır).
            var envelopeJson = MessageType("agent.run.progressed", unknownRunId, 1,
                new { event_sequence = 1, kind = "run_started", message = "bilinmeyen run" }, messageId);
            await PublishAsync(conversationId, correlationId, envelopeJson, messageId);
            // Kuyruk derinliği 0 olması teslim alındı demektir, işlendi değil; karantina
            // satırının commit'ini bekleriz (diğer senaryolar DB durumunu bekliyor).
            try
            {
                await WaitForAsync(async () =>
                {
                    await using var context = _fixture.CreateContext();
                    return await context.AgentEventInboxes.AsNoTracking()
                        .AnyAsync(i => i.MessageId == Guid.Parse(messageId) && i.Status == "quarantined");
                });
            }
            catch (TimeoutError)
            {
                await using var diagContext = _fixture.CreateContext();
                var allRows = await diagContext.AgentEventInboxes.AsNoTracking().ToListAsync();
                var dbName = diagContext.Database.GetConnectionString();
                Assert.Fail(
                    "karantina satırı zaman aşımında yazılmadı.\n" +
                    $"poll db: {dbName}\n" +
                    $"poll messageId: {messageId} / unknownRunId: {unknownRunId}\n" +
                    $"inbox satır sayısı: {allRows.Count}\n" +
                    "satırlar: " + string.Join(" | ", allRows.Select(r => $"{r.MessageId}/{r.RunId}/{r.Status}")) + "\n" +
                    "Consumer kayıtları:\n" + string.Join("\n", logs.Entries.TakeLast(40)));
            }
        }
        finally
        {
            await consumer.StopAsync();
        }

        // Sınırlı politika: sonsuz retry yok — kalıcı quarantine kaydı yazıldı ve mesaj ACK'landı.
        await using var context = _fixture.CreateContext();
        var quarantined = await context.AgentEventInboxes.AsNoTracking()
            .SingleAsync(i => i.MessageId == Guid.Parse(messageId));
        Assert.Equal("quarantined", quarantined.Status);
        Assert.Equal(unknownRunId, quarantined.RunId);
        Assert.False(await context.AgentRuns.AsNoTracking().AnyAsync(r => r.Id == unknownRunId));
    }

    [Fact]
    public async Task ContractViolation_GoesToDeadLetterWithoutProjectionChange()
    {
        await _fixture.ResetAsync();
        await _fixture.PurgeQueuesAsync();
        var (runId, conversationId, correlationId) = (Guid.NewGuid(), Guid.NewGuid(), Guid.NewGuid());
        await SeedRunAsync(runId);

        await using var host = BuildHost(new RecordingNotifier());
        var consumer = host.GetRequiredService<AgentEventProjectionConsumer>();
        await consumer.StartAsync();
        try
        {
            // Şemaya aykırı payload: selected_mode izinli küme dışı (kalıcı ihlal).
            var body = Encoding.UTF8.GetBytes(MessageType("agent.run.progressed", runId, 1,
                new { event_sequence = 1, kind = "not_a_kind", message = "zehirli olay" }));
            await PublishRawAsync("blog.agent.events", "agent.run.progressed.v1", body,
                Guid.NewGuid().ToString("D"), correlationId.ToString("D"), "agent.run.progressed");

            await WaitForAsync(async () =>
                await _fixture.QueueDepthAsync(AgentMessagingTopology.DeadLetterQueueFor(AgentMessagingTopology.BackendEventsQueue)) == 1,
                timeoutSeconds: 20);
        }
        finally
        {
            await consumer.StopAsync();
        }

        // Projection değişmedi; ana kuyruk boş.
        await using var context = _fixture.CreateContext();
        var run = await context.AgentRuns.AsNoTracking().SingleAsync(r => r.Id == runId);
        Assert.Equal(AgentRunStatus.Accepted, run.Status);
        Assert.Equal(0, await _fixture.QueueDepthAsync(AgentMessagingTopology.BackendEventsQueue));
    }

    // ------------------------------------------------------------ yardımcılar

    [Theory]
    [InlineData(1, true)]
    [InlineData(3, false)]
    public async Task InfrastructureFailures_RetryOriginalDelivery_ThenApplyOrDeadLetter(int failures, bool succeeds)
    {
        await _fixture.ResetAsync();
        await _fixture.PurgeQueuesAsync();
        var runId = Guid.NewGuid();
        await SeedRunAsync(runId);
        var messageId = Guid.NewGuid().ToString("D");
        var notifier = new RecordingNotifier();
        var faults = new TransientFailureInterceptor(failures);
        await using var host = BuildHost(notifier, faults: faults);
        var consumer = host.GetRequiredService<AgentEventProjectionConsumer>();
        await consumer.StartAsync();
        try
        {
            await PublishAsync(Guid.NewGuid(), Guid.NewGuid(), MessageType(
                "agent.run.completed", runId, 1, CompletedPayload(runId, 1), messageId), messageId);
            if (succeeds)
            {
                await WaitForAsync(async () => await RunStatusAsync(runId) == AgentRunStatus.Completed);
                await WaitForAsync(() => Task.FromResult(notifier.Count == 1));
            }
            else
            {
                await WaitForAsync(async () => await _fixture.QueueDepthAsync(
                    AgentMessagingTopology.DeadLetterQueueFor(AgentMessagingTopology.BackendEventsQueue)) == 1);
            }
        }
        finally
        {
            await consumer.StopAsync();
        }

        await using var verify = _fixture.CreateContext();
        var inbox = await verify.AgentEventInboxes.Where(i => i.RunId == runId).ToListAsync();
        if (succeeds)
        {
            Assert.Equal(Guid.Parse(messageId), Assert.Single(inbox).MessageId);
            Assert.Equal(0, await _fixture.QueueDepthAsync(
                AgentMessagingTopology.DeadLetterQueueFor(AgentMessagingTopology.BackendEventsQueue)));
        }
        else
        {
            Assert.Empty(inbox);
            Assert.Equal(AgentRunStatus.Accepted, await RunStatusAsync(runId));
            Assert.Equal(0, notifier.Count);
        }
        Assert.Equal(failures, faults.FailuresThrown);
    }

    private sealed class TransientFailureInterceptor(int failures) : DbCommandInterceptor
    {
        private int _calls;
        public int FailuresThrown { get; private set; }

        public override ValueTask<InterceptionResult<DbDataReader>> ReaderExecutingAsync(
            DbCommand command, CommandEventData eventData, InterceptionResult<DbDataReader> result,
            CancellationToken cancellationToken = default)
        {
            if (command.CommandText.Contains("agent_event_inbox", StringComparison.Ordinal)
                && Interlocked.Increment(ref _calls) <= failures)
            {
                FailuresThrown++;
                throw new TimeoutException("Injected temporary projection database outage.");
            }
            return ValueTask.FromResult(result);
        }
    }

    private ServiceProvider BuildHost(RecordingNotifier notifier, MemoryLogProvider? logs = null,
        TransientFailureInterceptor? faults = null)
    {
        var services = new ServiceCollection();
        // B9 additive: consumer'ın AgentCollaborationSettings IOptions bağımlılığı için.
        services.AddOptions();
        services.AddLogging(logging =>
        {
            if (logs is not null)
            {
                logging.AddProvider(logs);
            }
        });
        var brokerSettings = _fixture.BackendSettings();
        brokerSettings.RetryTierSeconds = [1, 1];
        services.AddSingleton(brokerSettings);
        services.AddSingleton<IRabbitMqConnectionManager, RabbitMqConnectionManager>();
        services.AddDbContext<AppDbContext>(options =>
        {
            options.UseNpgsql(_fixture.TestConnectionString, npgsql =>
                npgsql.MigrationsAssembly(typeof(AppDbContext).Assembly.FullName));
            if (faults is not null) options.AddInterceptors(faults);
        });
        services.AddScoped<IApplicationDbContext>(sp => sp.GetRequiredService<AppDbContext>());
        services.AddScoped<IUnitOfWork, UnitOfWork>();
        services.AddSingleton<IAgentRunNotifier>(notifier);
        services.AddSingleton(new AgentContractValidator());
        // B9 additive: projection işleyicisi proposal upsert'i için store'a bağlıdır.
        services.AddScoped<BlogApp.Core.Application.Features.AgentFeature.Collaboration.IAgentCollaborationStore,
            BlogApp.Infrastructure.Messaging.EfAgentCollaborationStore>();
        // W6 F6: terminal bildirim push'ı GET ile aynı sunum denetiminden geçer.
        services.AddScoped<BlogApp.Core.Application.Features.AgentFeature.Services.IAgentResultPresentationGuard,
            BlogApp.Core.Application.Features.AgentFeature.Services.AgentResultPresentationGuard>();
        services.AddScoped<AgentRunEventProjectionHandler>();
        services.AddSingleton<AgentEventProjectionConsumer>();
        return services.BuildServiceProvider();
    }

    private async Task SeedRunAsync(Guid runId)
    {
        await using var context = _fixture.CreateContext();
        await AgentRunSeeder.SeedAsync(context, runId);
    }

    private async Task<AgentRunStatus> RunStatusAsync(Guid runId)
    {
        await using var context = _fixture.CreateContext();
        var status = await context.AgentRuns.AsNoTracking()
            .Where(r => r.Id == runId)
            .Select(r => (AgentRunStatus?)r.Status)
            .SingleOrDefaultAsync();
        return status ?? AgentRunStatus.Accepted;
    }

    private async Task<long> LastSequenceAsync(Guid runId)
    {
        await using var context = _fixture.CreateContext();
        return await context.AgentRuns.AsNoTracking()
            .Where(r => r.Id == runId)
            .Select(r => r.LastEventSequence)
            .SingleAsync();
    }

    private static async Task WaitForAsync(Func<Task<bool>> condition, int timeoutSeconds = 15)
    {
        var deadline = DateTime.UtcNow.AddSeconds(timeoutSeconds);
        while (DateTime.UtcNow < deadline)
        {
            if (await condition())
            {
                return;
            }
            await Task.Delay(100);
        }
        throw new TimeoutError("koşul zaman aşımında sağlanmadı");
    }

    private static string OccurredNow() =>
        DateTime.UtcNow.ToString("yyyy-MM-dd'T'HH:mm:ss'Z'");

    private static string MessageType(string type, Guid runId, long sequenceIgnored, object payload, string? messageId = null) =>
        BuildEnvelope(type, runId, payload, messageId);

    private static string BuildEnvelope(string type, Guid runId, object payload, string? messageId)
    {
        var envelope = new Dictionary<string, object?>
        {
            ["message_id"] = messageId ?? Guid.NewGuid().ToString("D"),
            ["message_type"] = type,
            ["schema_version"] = 1,
            ["run_id"] = runId.ToString("D"),
            ["conversation_id"] = Guid.NewGuid().ToString("D"),
            ["correlation_id"] = Guid.NewGuid().ToString("D"),
            ["occurred_at"] = OccurredNow(),
            ["producer"] = "agent-py",
            ["payload"] = payload,
        };
        return JsonSerializer.Serialize(envelope);
    }

    private static object CompletedPayload(Guid runId, long sequence) => new
    {
        event_sequence = sequence,
        selected_mode = "fast",
        answer = "B5 backend test yanıtı",
        source_scope = "article",
        citations = new object[]
        {
            new { kind = "article", article_id = Guid.NewGuid().ToString("D"), article_revision = 1, chunk_index = 0 }
        },
        usage = new
        {
            run_id = runId.ToString("D"),
            total_tokens = 12,
            recorded_at = OccurredNow(),
        },
    };

    private static async Task PublishAsync(
        Guid conversationId, Guid correlationIgnored, string envelopeJson, string? messageId = null)
    {
        using var document = JsonDocument.Parse(envelopeJson);
        var correlationId = document.RootElement.GetProperty("correlation_id").GetString()!;
        var id = messageId ?? document.RootElement.GetProperty("message_id").GetString()!;
        var type = document.RootElement.GetProperty("message_type").GetString()!;
        await PublishRawAsync("blog.agent.events", $"{type}.v1", Encoding.UTF8.GetBytes(envelopeJson),
            id, correlationId, type);
    }

    private static async Task PublishRawAsync(
        string exchange, string routingKey, byte[] body, string messageId, string correlationId, string type)
    {
        var settings = ServiceLocatorFixtureAgentSettings();
        await using var connections = new RabbitMqConnectionManager(settings);
        await using var publisher = new RabbitMqAgentPublisher(connections, settings, [exchange]);
        await publisher.StartAsync();
        var result = await publisher.PublishAsync(exchange, routingKey, body, messageId, correlationId, type);
        Assert.True(result.Confirmed, $"test yayını confirm almadı: {result.Detail}");
    }

    private static RabbitMqSettings ServiceLocatorFixtureAgentSettings() => new()
    {
        Host = BrokerTestEnvironment.Host,
        Port = BrokerTestEnvironment.Port,
        UserName = "agent_svc",
        Password = "agent_svc_dev",
        VirtualHost = AgentEventProjectionFixture.TestVirtualHost,
        ClientProvidedName = "agent-py-b5-tests-publish",
    };
}

/// <summary>Zaman aşımı sinyali (test kapsamı).</summary>
public sealed class TimeoutError(string message) : Exception(message);
