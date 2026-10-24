using System.Diagnostics;
using System.Text;
using System.Text.Json;
using BlogApp.BuildingBlocks.Messaging;
using BlogApp.Core.Application.Common.Errors;
using BlogApp.Core.Application.Common.Interfaces.Services;
using BlogApp.Core.Application.Common.Messaging;
using BlogApp.Core.Application.Common.Options;
using BlogApp.Core.Application.Features.AgentFeature.Commands.AcceptAgentRunCommand;
using BlogApp.Core.Domain.Entities;
using BlogApp.Core.Domain.Enums;
using BlogApp.Infrastructure.Messaging;
using BlogApp.Infrastructure.Persistence;
using BlogApp.Infrastructure.Persistence.Repositories;
using BlogApp.Presentation.Api.Tests.Messaging.Broker;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging.Abstractions;
using Microsoft.Extensions.Options;
using Xunit;

namespace BlogApp.Presentation.Api.Tests.Messaging.Outbox;

/// <summary>
/// B3 kabul ölçütleri, gerçek Postgres + gerçek RabbitMQ 4.2 broker'ı üzerinde (plan satır 307):
/// 1. DB commit sonrası broker kapansa iş kaybolmaz.
/// 2. Publish sonrası confirm kaybı yalnız tekrar teslim üretir (aynı message_id).
/// 3. Rollback durumunda hayalet komut oluşmaz.
/// 4. Aynı kaydı iki publisher alamaz (FOR UPDATE SKIP LOCKED).
/// </summary>
[Collection("agent-rabbitmq-outbox")]
public class AgentOutboxRelayTests : IAsyncLifetime
{
    private readonly AgentOutboxDatabaseFixture _fixture;
    private static readonly TimeSpan TestTimeout = TimeSpan.FromMinutes(3);

    public AgentOutboxRelayTests(AgentOutboxDatabaseFixture fixture)
    {
        _fixture = fixture;
    }

    public async Task InitializeAsync()
    {
        await _fixture.ResetAsync();

        // relay'in passive declare'ı topology'nin varlığına dayanır; koleksiyon sırasına
        // güvenmeden idempotent kurulum (B2 kabul ölçütü: tekrarlı declare bozmaz).
        await using var initializer = new AgentTopologyInitializer(BrokerTestEnvironment.BackendSettings());
        await initializer.InitializeAsync(new CancellationTokenSource(TimeSpan.FromMinutes(2)).Token);
    }

    public Task DisposeAsync() => Task.CompletedTask;

    // ============================================== ölçüt 4: claim yarışı

    [Fact]
    public async Task ClaimBatch_ConcurrentPublishers_GetDisjointRecords()
    {
        await SeedPendingOutboxAsync(count: 8);

        await using var contextA = _fixture.CreateContext();
        await using var contextB = _fixture.CreateContext();
        var storeA = new OutboxClaimStore(contextA);
        var storeB = new OutboxClaimStore(contextB);

        var relay = RelaySettings();
        var claimA = storeA.ClaimBatchAsync("publisher-a", relay.BatchSize, TimeSpan.FromSeconds(60), NewToken());
        var claimB = storeB.ClaimBatchAsync("publisher-b", relay.BatchSize, TimeSpan.FromSeconds(60), NewToken());
        await Task.WhenAll(claimA, claimB);

        var idsA = claimA.Result.Select(r => r.Id).ToHashSet();
        var idsB = claimB.Result.Select(r => r.Id).ToHashSet();

        Assert.Empty(idsA.Intersect(idsB)); // hiçbir kayıt iki publishera düşmez
        Assert.Equal(8, idsA.Count + idsB.Count); // tüm kayıtlar tam bir tarafa

        await using var verify = _fixture.CreateContext();
        Assert.Equal(8, verify.OutboxMessages.Count(m => m.Status == AgentOutboxStatus.Claimed));
    }

    // ============================================== ölçüt 3: rollback → hayalet yok

    [Fact]
    public async Task TransactionWithoutCommit_PersistsNoRunAndNoCommand()
    {
        var context = _fixture.CreateContext();
        await using (context)
        await using (var transaction = await context.Database.BeginTransactionAsync())
        {
            context.AgentRuns.Add(MakeRun());
            context.OutboxMessages.Add(MakeOutbox());
            await context.SaveChangesAsync();
            // commit yok — istisna/çöküş benzeti; dispose rollback yapar
        }

        await using var verify = _fixture.CreateContext();
        Assert.Equal(0, verify.AgentRuns.Count());
        Assert.Equal(0, verify.OutboxMessages.Count());
    }

    [Fact]
    public async Task Accept_LosingUniqueTurnRace_RollsBackGhostCommand()
    {
        // Aynı konuşmada eşzamanlı kabul yarışının deterministik kurulumu: öteki transaction
        // (C, turn=1) kaydını commit ETMEDEN tutar; handler aynı turu hesaplayıp unique index'te
        // kilit bekler; öteki taraf commit edince handler'ın yazımı DbUpdateException ile döner
        // ve handler'ın transaction'ı ROLLBACK olur → outbox kaydı da geri alınır.
        var user = await _fixture.SeedUserAsync("race-user");
        var conversationId = Guid.NewGuid();

        var blocker = _fixture.CreateContext();
        await using (blocker)
        {
            await using var blockerTx = await blocker.Database.BeginTransactionAsync();
            blocker.AgentRuns.Add(MakeRun(
                conversationId,
                turnSequence: 1,
                ownerKey: $"u:{user.Id:D}",
                idempotencyKey: "seed-turn"));
            await blocker.SaveChangesAsync();

            var handler = CreateHandler(user.Id);
            var request = ValidRequest("race-loser") with { ConversationId = conversationId };

            var acceptTask = handler.Handle(request, CancellationToken.None);

            // Deterministik yarış: handler'ın unique index (ConversationId, TurnSequence)
            // beklemesini pg_stat_activity üzerinden aktif olarak tespit edene dek bekle;
            // ancak kaybeden taraf INSERT'te kilitteyken kazananı commit et.
            var blockedSeen = await WaitForAsync(() =>
            {
                using var probe = _fixture.CreateContext();
                var lockWaiters = probe.Database
                    .SqlQueryRaw<int>(
                        "SELECT count(*)::int AS \"Value\" FROM pg_stat_activity " +
                        "WHERE datname = current_database() AND wait_event_type = 'Lock' " +
                        "AND pid <> pg_backend_pid()")
                    .ToList();
                return lockWaiters.Single() > 0;
            }, TimeSpan.FromSeconds(30));
            Assert.True(blockedSeen, "handler 30 sn içinde unique index kilidine ulaşmadı");

            await blockerTx.CommitAsync(); // kazanan taraf
            var result = await acceptTask;

            Assert.True(result.IsFailure, result.IsSuccess ? $"kaybeden kabul başarıyla döndü: turn={result.Value!.TurnSequence}" : (result.ErrorDetail?.ToString() ?? "bilinmeyen hata"));
            Assert.Equal(ErrorCategory.Conflict, result.ErrorDetail!.Category);
        }

        await using var verify = _fixture.CreateContext();
        Assert.Equal(1, verify.AgentRuns.Count()); // yalnız kazanan seed kaydı
        Assert.Equal(0, verify.OutboxMessages.Count()); // hayalet komut YOK
    }

    // ============================================== ölçüt 1: broker kapansa iş kaybolmaz

    [Fact]
    public async Task BrokerOutage_AfterDbCommit_WorkNotLost_ThenPublished()
    {
        await PurgeExecuteQueueWhileBrokerUp();

        // 1) broker gerçekten kapalıyken kabul — kabul broker'a dokunmaz, yalnız DB'ye yazar
        RabbitMqCtl("stop_app");
        try
        {
            var user = await _fixture.SeedUserAsync("outage-user");
            var handler = CreateHandler(user.Id);
            var accept = await handler.Handle(ValidRequest("outage-1"), CancellationToken.None);
            Assert.True(accept.IsSuccess, "broker kapalıyken kabul başarısız olmamalı");

            // 2) commit sonrası kanıt: run + outbox kaydı DB'de, broker'a hiçbir şey gitmedi
            var messageId = await OutboxMessageIdOfAsync(accept.Value!.RunId);
            await using (var check = _fixture.CreateContext())
            {
                Assert.Equal(1, check.AgentRuns.Count(r => r.Id == accept.Value.RunId));
                var pending = check.OutboxMessages.Single(m => m.RunId == accept.Value.RunId);
                Assert.Equal(AgentOutboxStatus.Pending, pending.Status);
            }

            // 3) broker geri gelsin; relay kaydı yayınlasın
            RabbitMqCtl("start_app");
            await WaitForBrokerUpAsync();

            await using (var relay = BuildRelayHost())
            {
                await relay.StartAsync(NewToken());
                var published = await WaitForAsync(() =>
            {
                    using var context = _fixture.CreateContext();
                    var message = context.OutboxMessages.Single(m => m.RunId == accept.Value!.RunId);
                    return message.Status == AgentOutboxStatus.Published;
                }, TimeSpan.FromSeconds(90));
                Assert.True(published, $"broker dönüşünden sonra kayıt yayınlanmadı; outbox: {OutboxRowSnapshot(accept.Value!.RunId)}");
                await relay.StopAsync(NewToken());
            }

            var fetched = new List<FetchedMessage>();
            await CollectQueueUntilAsync(fetched, seen => seen.Any(m => m.MessageId == messageId),
                TimeSpan.FromSeconds(30));
            Assert.Contains(fetched, m => m.MessageId == messageId);
        }
        finally
        {
            RabbitMqCtl("start_app"); // diğer testler için broker ayakta kalsın
            await WaitForBrokerUpAsync();
        }
    }

    // ============================================== ölçüt 2: confirm kaybı → yalnız tekrar teslim

    [Fact]
    public async Task ConfirmLoss_RedeliversOnlyWithSameMessageId()
    {
        await PurgeExecuteQueueWhileBrokerUp();

        var user = await _fixture.SeedUserAsync("confirm-user");
        var handler = CreateHandler(user.Id);
        var accept = await handler.Handle(ValidRequest("confirm-1"), CancellationToken.None);
        Assert.True(accept.IsSuccess);
        var messageId = await OutboxMessageIdOfAsync(accept.Value!.RunId);

        // 1) ilk yayın: confirm'lu, kayıt Published, ilk transport sayacı 0.
        //    Not: confirm, ConfirmTimeout'u aşarsa relay yayını başarısız sayar ama mesaj
        //    kuyruğa düşmüş olabilir (karanlık bölge); tasarım buna AYNI message_id ile
        //    tekrar teslimle yanıt verir. Bu yüzden test tam kopya sayısı varsaymaz;
        //    message_id korunumunu ve artan delivery_attempt dizisini doğrular.
        var seenCopies = new List<FetchedMessage>();
        await using (var relay = BuildRelayHost())
        {
            await relay.StartAsync(NewToken());
            var published = await WaitForAsync(() =>
            {
                using var context = _fixture.CreateContext();
                var message = context.OutboxMessages.Single(m => m.RunId == accept.Value!.RunId);
                return message.Status == AgentOutboxStatus.Published;
            }, TimeSpan.FromSeconds(90));
            Assert.True(published, $"ilk yayın tamamlanmadı; outbox durumu: {OutboxRowSnapshot(accept.Value.RunId)}");
            await relay.StopAsync(NewToken());
        }

        await CollectQueueUntilAsync(seenCopies, seen => seen.Any(m => m.MessageId == messageId),
            TimeSpan.FromSeconds(30));
        Assert.True(seenCopies.Count > 0, $"ilk yayın kuyrukta bulunamadı; outbox: {OutboxRowSnapshot(accept.Value.RunId)}");
        Assert.Equal(0, DeliveryAttemptOf(seenCopies[0])); // ilk teslimat sayacı 0

        // 2) confirm kaybı benzetimi: kayıt, lease'i dolmuş bir Claimed gibi bırakılır
        //    (mesaj broker'a ulaşmış ama confirm kaybolmuş karanlık bölge; plan satır 301)
        await using (var context = _fixture.CreateContext())
        {
            await context.Database.ExecuteSqlRawAsync("""
                UPDATE outbox_messages
                SET "Status" = 'Claimed',
                    "ClaimedBy" = 'lost-confirm',
                    "ClaimedAt" = now() - interval '10 seconds',
                    "ClaimLeaseUntil" = now() - interval '5 seconds',
                    "PublishedAt" = NULL,
                    "AttemptCount" = 1
                WHERE "RunId" = {0}
                """, accept.Value.RunId);
        }

        // 3) tekrar yayın: AYNI message_id ile (consumer inbox tekilleştirmesi B4'te)
        await using (var relay = BuildRelayHost())
        {
            await relay.StartAsync(NewToken());
            var redelivered = await WaitForAsync(() =>
            {
                using var context = _fixture.CreateContext();
                var message = context.OutboxMessages.Single(m => m.RunId == accept.Value!.RunId);
                return message.Status == AgentOutboxStatus.Published && message.AttemptCount >= 2;
            }, TimeSpan.FromSeconds(90));
            Assert.True(redelivered,
                $"confirm kaybı sonrası kayıt tekrar yayınlanmadı; outbox: {OutboxRowSnapshot(accept.Value!.RunId)}");
            await relay.StopAsync(NewToken());
        }

        await CollectQueueUntilAsync(seenCopies, seen => seen.Count(m => m.MessageId == messageId) >= 2,
            TimeSpan.FromSeconds(30));

        // 4) ölçüt: HER kopya aynı message_id'yi taşır; delivery_attempt monoton artar;
        //    en az bir tekrar teslim (attempt >= 1) vardır — kayıp yalnız tekrar teslim üretir.
        var copies = seenCopies.Where(m => m.MessageId == messageId).ToList();
        Assert.True(copies.Count >= 2,
            $"tekrar teslim kuyrukta görülemedi; toplanan: {Describe(seenCopies)}; outbox: {OutboxRowSnapshot(accept.Value!.RunId)}");
        Assert.All(copies, copy => Assert.Equal(messageId, copy.MessageId));
        Assert.All(copies, copy => Assert.Equal("agent.execute.requested.v1", copy.RoutingKey));
        var attempts = copies.Select(DeliveryAttemptOf).ToList();
        Assert.Equal(0, attempts[0]); // ilk teslimat 0'dan başlar
        Assert.Equal(attempts, attempts.OrderBy(a => a).Distinct().ToList()); // her teslimde +1, atlama yok
        Assert.Equal(attempts.Count - 1, attempts.Last()); // son sayaç = kopya sayısı - 1 (0 tabanlı dizilim)
    }

    // ============================================== relay uçtan uca yayın

    [Fact]
    public async Task Relay_PublishesPendingRecord_WithConfirmAndAmqpProperties()
    {
        await PurgeExecuteQueueWhileBrokerUp();

        var user = await _fixture.SeedUserAsync("relay-user");
        var handler = CreateHandler(user.Id);
        var accept = await handler.Handle(ValidRequest("relay-1"), CancellationToken.None);
        Assert.True(accept.IsSuccess);
        var messageId = await OutboxMessageIdOfAsync(accept.Value!.RunId);

        await using (var relay = BuildRelayHost())
        {
            await relay.StartAsync(NewToken());
            var published = await WaitForAsync(() =>
            {
                using var context = _fixture.CreateContext();
                var message = context.OutboxMessages.Single(m => m.RunId == accept.Value!.RunId);
                return message.Status == AgentOutboxStatus.Published && message.ClaimedBy == null;
            }, TimeSpan.FromSeconds(90));
            Assert.True(published, $"yayın tamamlanmadı; outbox: {OutboxRowSnapshot(accept.Value!.RunId)}");
            await relay.StopAsync(NewToken());
        }

        var fetched = new List<FetchedMessage>();
        await CollectQueueUntilAsync(fetched, seen => seen.Any(m => m.MessageId == messageId),
            TimeSpan.FromSeconds(30));
        var message = fetched.Single(m => m.MessageId == messageId);

        Assert.Equal("agent.execute.requested.v1", message.RoutingKey);
        Assert.Equal("agent.execute.requested", message.Type);
        Assert.Equal(0, DeliveryAttemptOf(message)); // ilk yayında transport sayacı 0

        var validation = new AgentContractValidator(new AgentMessagingSettings()).Validate(message.BodyUtf8);
        Assert.True(validation.IsValid, $"kuyruktaki zarf sözleşme dışı: {validation.Error?.ToString()}");
        Assert.Equal(accept.Value!.RunId.ToString("D"), validation.Envelope!.RunId);
    }

    // ============================================== yardımcılar

    private AcceptAgentRunCommandHandler CreateHandler(Guid userId)
    {
        var context = _fixture.CreateContext();
        return new AcceptAgentRunCommandHandler(
            new UnitOfWork(context),
            context,
            new RelayTestCurrentUser(userId),
            new EfOutboxWriter(context),
            Options.Create(new AgentAcceptanceSettings { AllowGuestRuns = true, MaxActiveRunsPerOwner = 5 }),
            Options.Create(new AgentMessagingSettings()),
            NullLogger<AcceptAgentRunCommandHandler>.Instance);
    }

    private static AcceptAgentRunCommandRequest ValidRequest(string idempotencyKey) => new()
    {
        Question = "Relay test sorusu: bu makaleyi özetler misin?",
        Language = "tr",
        ModePreference = "fast",
        BudgetProfile = "standard",
        IdempotencyKey = idempotencyKey,
    };

    private static AgentRun MakeRun(
        Guid? conversationId = null,
        long turnSequence = 1,
        string ownerKey = "u:00000000-0000-0000-0000-000000000001",
        string idempotencyKey = "seed") => new()
    {
        ConversationId = conversationId ?? Guid.NewGuid(),
        TurnSequence = turnSequence,
        OwnerKey = ownerKey,
        IdempotencyKey = idempotencyKey,
        IdempotencyPayloadHash = "seed",
        Status = AgentRunStatus.Accepted,
        Question = "seed",
        Language = "tr",
        ModePreference = "auto",
        BudgetProfile = "standard",
        ContextSnapshotReference = $"agent-run/{Guid.NewGuid():D}/turn/1",
        ContextSnapshotJson = "{}",
        DeadlineAt = DateTime.UtcNow.AddMinutes(5),
        AcceptedAt = DateTime.UtcNow,
    };

    private static OutboxMessage MakeOutbox() => new()
    {
        MessageId = Guid.NewGuid().ToString("D"),
        MessageType = AgentMessageTypes.ExecutionRequested,
        Exchange = AgentMessageTypeRegistry.CommandsExchange,
        RoutingKey = "agent.execute.requested.v1",
        CorrelationId = Guid.NewGuid().ToString("D"),
        EnvelopeJson = "{}",
        Status = AgentOutboxStatus.Pending,
    };

    private async Task SeedPendingOutboxAsync(int count)
    {
        using var context = _fixture.CreateContext();
        for (var i = 0; i < count; i++)
        {
            context.OutboxMessages.Add(MakeOutbox());
        }

        await context.SaveChangesAsync();
    }

    private async Task<string> OutboxMessageIdOfAsync(Guid runId)
    {
        using var context = _fixture.CreateContext();
        return await context.OutboxMessages
            .Where(m => m.RunId == runId)
            .Select(m => m.MessageId)
            .SingleAsync();
    }

    private AgentOutboxRelaySettings RelaySettings() => new()
    {
        BatchSize = 8,
        PollIntervalSeconds = 1,
        // Kısa lease: beginersiz deneme sonrası hızlı geri alma. Confirm toleransı yüksek:
        // tam suite yükünde confirm gecikirse relay yayını başarısız sayar; bu SENARYO
        // (karanlık bölge) tekrar teslimle karşılanır ve test bunu doğrulayacak şekilde yazıldı.
        ClaimLeaseSeconds = 10,
        ConfirmTimeoutSeconds = 15,
        MaxAttempts = 12,
        InstanceName = "relay-tests",
    };

    /// <summary>Gerçek relay hosted service; test DB'si ve gerçek broker ile kurulur.</summary>
    private RelayHost BuildRelayHost()
    {
        var brokerSettings = BrokerTestEnvironment.BackendSettings();
        var relay = RelaySettings();
        var services = new ServiceCollection();
        services.AddSingleton(brokerSettings);
        services.AddSingleton<IRabbitMqConnectionManager, RabbitMqConnectionManager>();
        services.AddSingleton<RabbitMqAgentPublisher>(sp => new RabbitMqAgentPublisher(
            sp.GetRequiredService<IRabbitMqConnectionManager>(),
            sp.GetRequiredService<RabbitMqSettings>(),
            [AgentMessagingTopology.CommandsExchange, AgentMessagingTopology.ContentExchange]));
        services.AddLogging();
        services.Configure<AgentOutboxRelaySettings>(o =>
        {
            o.BatchSize = relay.BatchSize;
            o.PollIntervalSeconds = relay.PollIntervalSeconds;
            o.ClaimLeaseSeconds = relay.ClaimLeaseSeconds;
            o.ConfirmTimeoutSeconds = relay.ConfirmTimeoutSeconds;
            o.MaxAttempts = relay.MaxAttempts;
            o.InstanceName = relay.InstanceName;
        });
        services.AddDbContext<AppDbContext>(o => o.UseNpgsql(
            _fixture.TestConnectionString,
            npgsql => npgsql.MigrationsAssembly(typeof(AppDbContext).Assembly.FullName)));
        services.AddHostedService<OutboxRelayService>();

        return new RelayHost(services.BuildServiceProvider());
    }

    private static CancellationToken NewToken() =>
        new CancellationTokenSource(TestTimeout).Token;

    private static async Task<bool> WaitForAsync(Func<bool> condition, TimeSpan timeout)
    {
        var deadline = DateTime.UtcNow + timeout;
        while (DateTime.UtcNow < deadline)
        {
            if (condition())
            {
                return true;
            }

            await Task.Delay(250);
        }

        return condition();
    }

    /// <summary>Kuyruğu tekrar tekrar boşaltıp toplanan mesajları biriktirir; koşul sağlanana
    /// ya da zaman aşımına kadar döner. Broker görünürlük gecikmelerini tolerlar.</summary>
    private static async Task CollectQueueUntilAsync(
        List<FetchedMessage> accumulator,
        Func<List<FetchedMessage>, bool> condition,
        TimeSpan timeout)
    {
        var deadline = DateTime.UtcNow + timeout;
        while (DateTime.UtcNow < deadline)
        {
            accumulator.AddRange(await DrainExecuteQueueAsync());
            if (condition(accumulator))
            {
                return;
            }

            await Task.Delay(500);
        }

        accumulator.AddRange(await DrainExecuteQueueAsync());
    }

    private string OutboxRowSnapshot(Guid runId)
    {
        using var context = _fixture.CreateContext();
        var message = context.OutboxMessages.Single(m => m.RunId == runId);
        return $"status={message.Status} attempt={message.AttemptCount} " +
               $"lease={message.ClaimLeaseUntil:O} err={message.LastError ?? "-"}";
    }

    private static string Describe(IEnumerable<FetchedMessage> messages) =>
        string.Join(", ", messages.Select(m => $"(id={m.MessageId?[..8]}..., attempt={SafeDeliveryAttempt(m)})"));

    private static int SafeDeliveryAttempt(FetchedMessage message)
    {
        try
        {
            return DeliveryAttemptOf(message);
        }
        catch
        {
            return -1;
        }
    }

    // ------------------------------------------------------------ broker yardımcıları

    private static void RabbitMqCtl(string arguments)
    {
        var psi = new ProcessStartInfo
        {
            FileName = "docker",
            Arguments = $"exec {BrokerTestEnvironment.RabbitMqContainer} rabbitmqctl {arguments}",
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            UseShellExecute = false,
        };
        using var process = Process.Start(psi)!;
        process.WaitForExit(120_000);
        Assert.True(process.ExitCode == 0,
            $"rabbitmqctl {arguments} başarısız: {process.StandardError.ReadToEnd()}");
    }

    private static async Task WaitForBrokerUpAsync()
    {
        var deadline = DateTime.UtcNow + TimeSpan.FromMinutes(2);
        while (DateTime.UtcNow < deadline)
        {
            try
            {
                await using var connection = await BrokerTestEnvironment.OpenAdminConnectionAsync(
                    new CancellationTokenSource(TimeSpan.FromSeconds(5)).Token,
                    "b3-broker-wait");
                return;
            }
            catch
            {
                await Task.Delay(1000);
            }
        }

        Assert.Fail("broker 2 dakikada ayakta gelmedi");
    }

    private async Task PurgeExecuteQueueWhileBrokerUp()
    {
        await WaitForBrokerUpAsync();
        await using var admin = await BrokerTestEnvironment.OpenAdminConnectionAsync(NewToken(), "b3-purge");
        await using var channel = await admin.CreateChannelAsync(cancellationToken: NewToken());
        await channel.QueuePurgeAsync(AgentMessagingTopology.ExecuteQueue, NewToken());
    }

    private static async Task<List<FetchedMessage>> DrainExecuteQueueAsync()
    {
        var messages = new List<FetchedMessage>();
        await using var admin = await BrokerTestEnvironment.OpenAdminConnectionAsync(NewToken(), "b3-drain");
        await using var channel = await admin.CreateChannelAsync(cancellationToken: NewToken());
        while (true)
        {
            var fetched = await channel.BasicGetAsync(AgentMessagingTopology.ExecuteQueue, autoAck: true, NewToken());
            if (fetched is null)
            {
                break;
            }

            messages.Add(new FetchedMessage(
                fetched.BasicProperties.MessageId,
                fetched.RoutingKey,
                fetched.BasicProperties.Type,
                fetched.Body.ToArray()));
        }

        return messages;
    }

    private static int DeliveryAttemptOf(FetchedMessage message)
    {
        using var document = JsonDocument.Parse(message.BodyUtf8);
        return document.RootElement.GetProperty("delivery_attempt").GetInt32();
    }

    private sealed record FetchedMessage(string? MessageId, string RoutingKey, string? Type, byte[] Body)
    {
        public string BodyUtf8 => Encoding.UTF8.GetString(Body);
    }

    private sealed class RelayTestCurrentUser(Guid userId) : ICurrentUserService
    {
        public Guid? UserId => userId;
        public string? UserName => "relay-test-user";
        public string? Email => null;
        public string? CorrelationId => null;
        public bool IsAuthenticated => true;
        public bool IsInRole(string role) => false;
    }

    private sealed class RelayHost(IServiceProvider provider) : IAsyncDisposable
    {
        public Task StartAsync(CancellationToken cancellationToken) =>
            provider.GetRequiredService<IHostedService>().StartAsync(cancellationToken);

        public Task StopAsync(CancellationToken cancellationToken) =>
            provider.GetRequiredService<IHostedService>().StopAsync(cancellationToken);

        public async ValueTask DisposeAsync()
        {
            if (provider is IAsyncDisposable asyncDisposable)
            {
                await asyncDisposable.DisposeAsync();
            }
            else if (provider is IDisposable disposable)
            {
                disposable.Dispose();
            }
        }
    }
}
