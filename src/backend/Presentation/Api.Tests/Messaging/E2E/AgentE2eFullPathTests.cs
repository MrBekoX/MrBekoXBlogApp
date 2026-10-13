using System.Diagnostics;
using System.Text;
using System.Text.Json;
using BlogApp.BuildingBlocks.Messaging;
using BlogApp.Core.Application.Common.Interfaces.Data;
using BlogApp.Core.Application.Common.Interfaces.Persistence;
using BlogApp.Core.Application.Common.Interfaces.Services;
using BlogApp.Core.Application.Common.Messaging;
using BlogApp.Core.Application.Common.Models;
using BlogApp.Core.Application.Common.Options;
using BlogApp.Core.Application.Features.AgentFeature.Commands.AcceptAgentRunCommand;
using BlogApp.Core.Application.Features.AgentFeature.Commands.CancelAgentRunCommand;
using BlogApp.Core.Application.Features.AgentFeature.Queries.GetAgentRunEventsQuery;
using BlogApp.Core.Application.Features.AgentFeature.Queries.GetAgentRunQuery;
using BlogApp.Core.Application.Features.AgentFeature.Services;
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

namespace BlogApp.Presentation.Api.Tests.Messaging.E2E;

/// <summary>
/// B11 bileşik uçtan uca testler (plan "BİRLEŞİK E2E" bileşeni; gerçek
/// RabbitMQ 4.2.9 + gerçek PostgreSQL). Model yolu test sağlayıcısıyla
/// DEĞİL, kablo sözleşmesiyle temsil edilir: worker graph'ı python e2e
/// suite'inde (tests/e2e) gerçek bileşenleriyle koşar; burada her iki yarımın
/// KABLO üstündeki karşılığı donuk B1 sözleşmesiyle doğrulanır. Gerçek LLM
/// olmadığından bu suite gerçek model davranışı iddia ETMEZ.
///
/// Kapsanan kullanıcı yolları (birleşik kapı maddeleri 1/5/6/8):
/// 1. makale bağlamıyla soru → kabul+outbox → broker → (kablo) → kaynaklı
///    cevap olayı → projection → GET run sonucu → replay aynı sonucu döner.
/// 2. iptal yolu: cancel outbox → cancelled olayı → terminal; geç completed reddi.
/// 3. kaldırılan içeriğe dayanan geç sonuç → sunum denetimi maskeleyerek
///    UnavailableReason döner (içerik sızmaz).
/// 4. broker kesintisi: kabul edilen iş "bekliyor" görünür; kesinti sonrası
///    backlog toparlanıp tüm kayıtlar kabloda görünür.
/// </summary>
[Collection("agent-e2e-b11")]
public sealed class AgentE2eFullPathTests : IAsyncLifetime
{
    private readonly AgentE2eFixture _fixture;
    private static readonly TimeSpan TestTimeout = TimeSpan.FromMinutes(3);

    public AgentE2eFullPathTests(AgentE2eFixture fixture)
    {
        _fixture = fixture;
    }

    public async Task InitializeAsync()
    {
        await _fixture.ResetAsync();
        await _fixture.PurgeQueuesAsync();
    }

    public Task DisposeAsync() => Task.CompletedTask;

    // ======================================= yol 1: makale sorusu → kaynaklı cevap

    [Fact]
    public async Task FullPath_ArticleQuestion_FlowsToProjectedSourcedAnswer_AndReplays()
    {
        // 1) GERÇEK kabul: oturum + yayımlanmış makale bağlamı + outbox TEK transaction.
        var user = await _fixture.SeedUserAsync("e2e-path-user");
        var post = await _fixture.SeedPublishedPostAsync(user.Id, "E2E Path Article");
        var accept = await AcceptAsync(user.Id, request => request with
        {
            Question = "Bu makalenin ana fikri nedir?",
            ArticleId = post.Id,
        });
        Assert.True(accept.IsSuccess, accept.ErrorDetail?.ToString() ?? "kabul başarısız");
        var runId = accept.Value!.RunId;

        // Kabul anında istemci yalnız "Accepted" görür (broker henüz kabloda değil).
        var beforePublish = await GetRunAsync(runId, user.Id);
        Assert.True(beforePublish.IsSuccess);
        Assert.Equal(AgentRunStatus.Accepted.ToString(), beforePublish.Value!.Status);
        Assert.Null(beforePublish.Value.Result);

        // 2) GERÇEK relay: outbox → confirm'lu broker yayını.
        await RunRelayUntilAsync(runId, AgentOutboxStatus.Published);

        // 3) KABLO doğrulaması: kuyruktan çekilen zarf B1 sözleşmesini geçer —
        //    python intake'in dayattığı doğrulamanın birebir karşılığı.
        var command = await FetchCommandFromQueueAsync();
        var outboxMessageId = await OutboxMessageIdOfAsync(runId);
        Assert.Equal(outboxMessageId, command.MessageId);
        var validation = new AgentContractValidator(new AgentMessagingSettings()).Validate(command.BodyUtf8);
        Assert.True(validation.IsValid, $"kablodaki komut sözleşme dışı: {validation.Error?.ToString()}");
        Assert.Equal(runId.ToString("D"), validation.Envelope!.RunId);

        // 4) Agent yarımı (kablo karşılığı): python AgentEventPublisher'ın olay
        //    akışı — önce agent.run.mode_selected (mod seçimi projection'da ayrı
        //    olaydan gelir), ardından kaynaklı agent.run.completed zarfı.
        await PublishAgentEventAsync(
            runId, beforePublish.Value!.ConversationId, "agent.run.mode_selected", sequence: 1,
            payload: new Dictionary<string, object?>
            {
                ["event_sequence"] = 1,
                ["selected_mode"] = "fast",
                ["requires_web_search"] = false,
                ["reason"] = "soru kısa; fast yeterli",
            });
        await PublishAgentEventAsync(
            runId, beforePublish.Value!.ConversationId, "agent.run.completed", sequence: 2,
            payload: new Dictionary<string, object?>
            {
                ["event_sequence"] = 2,
                ["selected_mode"] = "fast",
                ["answer"] = "E2E kaynaklı yanıt: makale B11 entegrasyon yolunu doğrular.",
                ["source_scope"] = "article",
                ["citations"] = new object[]
                {
                    new
                    {
                        kind = "article",
                        article_id = post.Id.ToString("D"),
                        article_revision = post.ContentRevision,
                        chunk_index = 0,
                    },
                },
                ["usage"] = new Dictionary<string, object?>
                {
                    ["run_id"] = runId.ToString("D"),
                    ["total_tokens"] = 42,
                    ["recorded_at"] = DateTime.UtcNow.ToString("yyyy-MM-dd'T'HH:mm:ss'Z'"),
                },
            });

        // 5) GERÇEK projection: olay kuyruğunu gerçek consumer tüketir.
        await ConsumeEventsUntilAsync(async () => await RunStatusAsync(runId) == AgentRunStatus.Completed);

        // 6) GERÇEK GET run: kaynaklı cevap + atıf sunulur.
        var after = await GetRunAsync(runId, user.Id);
        Assert.True(after.IsSuccess);
        Assert.Equal(AgentRunStatus.Completed.ToString(), after.Value!.Status);
        Assert.Equal("fast", after.Value.SelectedMode);
        Assert.NotNull(after.Value.Result);
        Assert.Null(after.Value.Result.UnavailableReason);
        Assert.Contains("E2E kaynaklı yanıt", after.Value.Result.Answer);
        Assert.Contains(after.Value.Result.Citations, c =>
            c.Kind == "article" && c.ArticleId == post.Id && c.ArticleRevision == post.ContentRevision);

        // 7) Yenileme/replay: events replay AYNI olay dizisini döner; GET run
        //    AYNI terminal sonucu taşır (sayfa yenileme yolu).
        var replay = await ReplayEventsAsync(runId, user.Id);
        Assert.True(replay.IsSuccess);
        Assert.Contains(replay.Value!.Events, e => e.MessageType == "agent.run.completed");
        var replayGet = await GetRunAsync(runId, user.Id);
        Assert.Equal(after.Value.Result!.Answer, replayGet.Value!.Result!.Answer);

        // Kuyruk boşaldı: ConsumeEventsUntilAsync consumer'ı durdurmadan ÖNCE
        // ready=0 VE unacked=0 doğrular; sakinleşmiş kapanışta requeue edilecek
        // teslim kalmaz, dolayısıyla bu son ready yoklaması kesindir (commit→ACK
        // yarışının bıraktığı "kuyrukta takılı mesaj" hatası yapısal olarak olanaksız).
        var drained = await WaitForAsync(EventsQueueDrainedAsync, TimeSpan.FromSeconds(15));
        Assert.True(drained, "olay kuyruğu projection sonrası boşalmadı (ACK gecikmesi)");
    }

    // ======================================= yol 2: iptal + geç completed reddi

    [Fact]
    public async Task FullPath_CancelPath_TerminalizesAndRejectsLateCompleted()
    {
        var user = await _fixture.SeedUserAsync("e2e-cancel-user");
        var post = await _fixture.SeedPublishedPostAsync(user.Id, "E2E Cancel Article");
        var accept = await AcceptAsync(user.Id, request => request with
        {
            Question = "İptal edilecek soru",
            ArticleId = post.Id,
        });
        Assert.True(accept.IsSuccess);
        var runId = accept.Value!.RunId;

        // Cancel komutu (B3 deseni): cancel intent değil — backend outbox cancel
        // komutu yazar; python tarafındaki terminal-öncelik kuralları B7'dedir.
        await using (var context = _fixture.CreateContext())
        {
            var cancelHandler = new CancelAgentRunCommandHandler(
                new UnitOfWork(context),
                context,
                new E2eCurrentUser(user.Id),
                new EfOutboxWriter(context),
                Options.Create(new AgentMessagingSettings()),
                NullLogger<CancelAgentRunCommandHandler>.Instance);
            var cancel = await cancelHandler.Handle(
                new CancelAgentRunCommandRequest { RunId = runId, Reason = "e2e iptal" },
                CancellationToken.None);
            Assert.True(cancel.IsSuccess, cancel.ErrorDetail?.ToString() ?? "iptal başarısız");
        }

        // Cancel komutu kabloda (relay gerçek).
        await RunRelayUntilMessageTypeAsync(runId, "cancel");

        // cancelled terminal olayı (python tarafının ürettiği zarf karşılığı).
        await PublishAgentEventAsync(runId, Guid.NewGuid(), "agent.run.cancelled", sequence: 1,
            payload: new Dictionary<string, object?>
            {
                ["event_sequence"] = 1,
                ["reason"] = "e2e iptal",
            });
        await ConsumeEventsUntilAsync(async () => await RunStatusAsync(runId) == AgentRunStatus.Cancelled);

        // GEÇ completed (cancel ile AYNI sequence yarışı — gerçekçi yarış):
        // terminal-öncelik kuralı eşit sequence'i stale sayar; durum gerilemez,
        // sonucun Answer alanı yazılmaz (ikiden yeni terminal yalnız B7 kuralındaki
        // "daha yüksek sequence kazanır" yoluyla gelir; bu test eşit-yarışın reddini
        // doğrular).
        await PublishAgentEventAsync(runId, Guid.NewGuid(), "agent.run.completed", sequence: 1,
            payload: new Dictionary<string, object?>
            {
                ["event_sequence"] = 1,
                ["selected_mode"] = "fast",
                ["answer"] = "iptalden SONRA gelen geç yanıt",
                ["source_scope"] = "article",
                ["usage"] = new Dictionary<string, object?>
                {
                    ["run_id"] = runId.ToString("D"),
                    ["total_tokens"] = 7,
                    ["recorded_at"] = DateTime.UtcNow.ToString("yyyy-MM-dd'T'HH:mm:ss'Z'"),
                },
            });
        await ConsumeEventsUntilAsync(EventsQueueDrainedAsync);

        var status = await GetRunAsync(runId, user.Id);
        Assert.Equal(AgentRunStatus.Cancelled.ToString(), status.Value!.Status); // gerileme yok
        // Geç completed İÇERİĞİ sunulmaz (ResultJson cancelled payload'ı taşır —
        // terminal olay snapshot'ı; "answer" alanı yoktur).
        Assert.Null(status.Value.Result?.Answer);
        Assert.DoesNotContain("iptalden SONRA gelen geç yanıt",
            JsonSerializer.Serialize(status.Value.Result ?? new AgentRunResultDto { Status = status.Value.Status }));

        // Canlı adım olay yüzeyi: replay'de cancelled olayı kind='cancelled'
        // ile akar (terminal kind messageType son ekinden türetilir); stale
        // completed replay'in parçası değildir.
        var replay = await ReplayEventsAsync(runId, user.Id);
        Assert.True(replay.IsSuccess);
        var cancelledReplay = Assert.Single(replay.Value!.Events);
        Assert.Equal("agent.run.cancelled", cancelledReplay.MessageType);
        Assert.Equal("cancelled", cancelledReplay.Kind);

        var run = await SingleRunAsync(runId);
        Assert.DoesNotContain("geç yanıt", run.ResultJson ?? string.Empty); // projection'a yazılmadı
    }

    // ======================================= yol 3: kaldırılan içerik → geç sonuç maskeli

    [Fact]
    public async Task FullPath_RemovedContent_LateResultIsMaskedWithReason()
    {
        var user = await _fixture.SeedUserAsync("e2e-stale-user");
        var post = await _fixture.SeedPublishedPostAsync(user.Id, "E2E Stale Article");
        var accept = await AcceptAsync(user.Id, request => request with
        {
            Question = "Kaldırılacak makale sorusu",
            ArticleId = post.Id,
        });
        Assert.True(accept.IsSuccess);
        var runId = accept.Value!.RunId;

        // Makale YAYINDAN KALDIRILIR (B8: tombstone olayı ayrı yoldadır; burada
        // sunum denetiminin gördüğü güncel yayın durumu değişir).
        await using (var context = _fixture.CreateContext())
        {
            var stored = await context.Posts.SingleAsync(p => p.Id == post.Id);
            stored.Unpublish();
            await context.SaveChangesAsync();
        }

        // Geç sonuç (kaldırma ANINDA uçuştaymış gibi) makale atfıyla gelir.
        await PublishAgentEventAsync(runId, Guid.NewGuid(), "agent.run.completed", sequence: 1,
            payload: new Dictionary<string, object?>
            {
                ["event_sequence"] = 1,
                ["selected_mode"] = "fast",
                ["answer"] = "kaldırılmış içeriğe dayanan yanıt",
                ["source_scope"] = "article",
                ["citations"] = new object[]
                {
                    new
                    {
                        kind = "article",
                        article_id = post.Id.ToString("D"),
                        article_revision = post.ContentRevision,
                        chunk_index = 0,
                    },
                },
                ["usage"] = new Dictionary<string, object?>
                {
                    ["run_id"] = runId.ToString("D"),
                    ["total_tokens"] = 11,
                    ["recorded_at"] = DateTime.UtcNow.ToString("yyyy-MM-dd'T'HH:mm:ss'Z'"),
                },
            });
        await ConsumeEventsUntilAsync(async () => await RunStatusAsync(runId) == AgentRunStatus.Completed);

        // Projection Completed kaydetti ama GET run içeriği MASKELEDİ: cevap
        // DÖNMEZ, yalnız kullanılamaz gerekçesi taşınır (plan satır 578).
        var status = await GetRunAsync(runId, user.Id);
        Assert.Equal(AgentRunStatus.Completed.ToString(), status.Value!.Status);
        Assert.NotNull(status.Value.Result);
        Assert.Null(status.Value.Result!.Answer);
        Assert.False(string.IsNullOrWhiteSpace(status.Value.Result.UnavailableReason));
        Assert.DoesNotContain("kaldırılmış içeriğe dayanan yanıt",
            JsonSerializer.Serialize(status.Value.Result));
    }

    // ======================================= yol 4: broker kesintisi → backlog → toparlanma

    [Fact]
    public async Task FullPath_BrokerOutage_RunsWaitVisibly_ThenBacklogRecovers()
    {
        RabbitMqCtl("stop_app");
        try
        {
            // Broker KAPALIYKEN üç kabul: kabul broker'a dokunmaz (B3 kabul ölçütü);
            // her run DB outbox'ında Pending kalır — "bekliyor" gösterimi.
            var user = await _fixture.SeedUserAsync("e2e-outage-user");
            var post = await _fixture.SeedPublishedPostAsync(user.Id, "E2E Outage Article");
            var runIds = new List<Guid>();
            foreach (var key in new[] { "outage-1", "outage-2", "outage-3" })
            {
                var accept = await AcceptAsync(user.Id, request => request with
                {
                    IdempotencyKey = key,
                    Question = $"kesinti sorusu {key}",
                    ArticleId = post.Id,
                });
                Assert.True(accept.IsSuccess, "broker kapalıyken kabul başarısız olmamalı");
                runIds.Add(accept.Value!.RunId);
            }

            foreach (var runId in runIds)
            {
                await using var check = _fixture.CreateContext();
                var pending = check.OutboxMessages.Single(m => m.RunId == runId);
                Assert.Equal(AgentOutboxStatus.Pending, pending.Status);
                var status = await GetRunAsync(runId, user.Id);
                Assert.Equal(AgentRunStatus.Accepted.ToString(), status.Value!.Status); // bekliyor
            }

            // Toparlanma: broker döner, GERÇEK relay backlog'u boşaltır.
            RabbitMqCtl("start_app");
            await WaitForBrokerUpAsync();
            using (var relay = BuildRelayHost())
            {
                await relay.StartAsync(NewToken());
                var drained = await WaitForAsync(() =>
                {
                    using var context = _fixture.CreateContext();
                    return context.OutboxMessages.Count(m =>
                        m.RunId != null && runIds.Contains(m.RunId.Value) &&
                        m.Status == AgentOutboxStatus.Published) == runIds.Count;
                }, TimeSpan.FromSeconds(90));
                Assert.True(drained, "broker dönüşünden sonra backlog tam boşalmadı");
                await relay.StopAsync(NewToken());
            }

            // Tüm komutlar kabloda görünüyor (aynı message_id'lerle).
            var seen = await DrainExecuteQueueAsync();
            foreach (var runId in runIds)
            {
                await using var context = _fixture.CreateContext();
                var messageId = await context.OutboxMessages
                    .Where(m => m.RunId == runId)
                    .Select(m => m.MessageId)
                    .SingleAsync();
                Assert.Contains(seen, m => m.MessageId == messageId);
            }
        }
        finally
        {
            RabbitMqCtl("start_app");
            await WaitForBrokerUpAsync();
        }
    }

    // ============================================================ yardımcılar

    private async Task<Result<AgentRunAcceptedDto>> AcceptAsync(
        Guid? userId, Func<AcceptAgentRunCommandRequest, AcceptAgentRunCommandRequest> mutate)
    {
        await using var context = _fixture.CreateContext();
        var handler = new AcceptAgentRunCommandHandler(
            new UnitOfWork(context),
            context,
            new E2eCurrentUser(userId),
            new EfOutboxWriter(context),
            Options.Create(new AgentAcceptanceSettings { AllowGuestRuns = true, MaxActiveRunsPerOwner = 5 }),
            Options.Create(new AgentMessagingSettings()),
            NullLogger<AcceptAgentRunCommandHandler>.Instance);

        var baseRequest = new AcceptAgentRunCommandRequest
        {
            Question = "E2E sorusu",
            Language = "tr",
            ModePreference = "fast",
            BudgetProfile = "standard",
            IdempotencyKey = $"e2e-{Guid.NewGuid():N}",
        };
        return await handler.Handle(mutate(baseRequest), CancellationToken.None);
    }

    private async Task<Result<AgentRunStatusDto>> GetRunAsync(Guid runId, Guid? userId)
    {
        await using var context = _fixture.CreateContext();
        var handler = new GetAgentRunQueryHandler(
            context,
            new E2eCurrentUser(userId),
            new AgentResultPresentationGuard(context));
        return await handler.Handle(new GetAgentRunQueryRequest { RunId = runId }, CancellationToken.None);
    }

    private async Task<Result<AgentRunEventsDto>> ReplayEventsAsync(Guid runId, Guid? userId)
    {
        await using var context = _fixture.CreateContext();
        var handler = new GetAgentRunEventsQueryHandler(context, new E2eCurrentUser(userId));
        return await handler.Handle(
            new GetAgentRunEventsQueryRequest { RunId = runId },
            CancellationToken.None);
    }

    private async Task<Core.Domain.Entities.AgentRun> SingleRunAsync(Guid runId)
    {
        await using var context = _fixture.CreateContext();
        return await context.AgentRuns.AsNoTracking().SingleAsync(r => r.Id == runId);
    }

    private async Task<AgentRunStatus> RunStatusAsync(Guid runId)
    {
        await using var context = _fixture.CreateContext();
        return await context.AgentRuns.AsNoTracking()
            .Where(r => r.Id == runId)
            .Select(r => r.Status)
            .SingleAsync();
    }

    private async Task<bool> EventsQueueDrainedAsync() =>
        await _fixture.QueueDepthAsync(AgentMessagingTopology.BackendEventsQueue) == 0;

    /// <summary>Gerçek OutboxRelayService; kayıt istenen duruma gelene dek çalışır.</summary>
    private async Task RunRelayUntilAsync(Guid runId, AgentOutboxStatus target) =>
        await RunRelayUntilAsync(runId, _ => true, target);

    private async Task RunRelayUntilMessageTypeAsync(Guid runId, string messageTypeFragment) =>
        await RunRelayUntilAsync(runId,
            message => (message.MessageType ?? string.Empty).Contains(messageTypeFragment, StringComparison.Ordinal),
            AgentOutboxStatus.Published);

    private async Task RunRelayUntilAsync(
        Guid runId, Func<Core.Domain.Entities.OutboxMessage, bool> predicate, AgentOutboxStatus target)
    {
        using var relay = BuildRelayHost();
        await relay.StartAsync(NewToken());
        try
        {
            var done = await WaitForAsync(() =>
            {
                using var context = _fixture.CreateContext();
                // Bir run birden çok outbox kaydı yazabilir (accept + cancel);
                // koşul: istenen tipte kayıt hedef durumda ve HEPSİ hedef durumda.
                var messages = context.OutboxMessages.AsNoTracking()
                    .Where(m => m.RunId == runId)
                    .ToList();
                return messages.Count > 0
                    && messages.All(m => m.Status == target)
                    && messages.Any(predicate);
            }, TimeSpan.FromSeconds(90));
            Assert.True(done, $"relay hedefe ulaşmadı (run {runId}, hedef {target})");
        }
        finally
        {
            await relay.StopAsync(NewToken());
        }
    }

    private RelayHost BuildRelayHost()
    {
        var brokerSettings = _fixture.BackendSettings();
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
            o.BatchSize = 8;
            o.PollIntervalSeconds = 1;
            o.ClaimLeaseSeconds = 10;
            o.ConfirmTimeoutSeconds = 15;
            o.MaxAttempts = 12;
            o.InstanceName = "b11-e2e-relay";
        });
        services.AddDbContext<AppDbContext>(o => o.UseNpgsql(
            _fixture.TestConnectionString,
            npgsql => npgsql.MigrationsAssembly(typeof(AppDbContext).Assembly.FullName)));
        services.AddHostedService<OutboxRelayService>();
        return new RelayHost(services.BuildServiceProvider());
    }

    /// <summary>Kuyruktan komut çeker (admin; python intake'in göreceği kablo).</summary>
    private async Task<WireCommand> FetchCommandFromQueueAsync()
    {
        var deadline = DateTime.UtcNow + TimeSpan.FromSeconds(30);
        while (DateTime.UtcNow < deadline)
        {
            var messages = await DrainExecuteQueueAsync();
            if (messages.Count > 0)
            {
                return messages[0];
            }

            await Task.Delay(400);
        }

        Assert.Fail("komut 30 sn içinde kuyrukta görünmedi");
        return null!;
    }

    private async Task<List<WireCommand>> DrainExecuteQueueAsync()
    {
        var messages = new List<WireCommand>();
        await using var admin = await _fixture.OpenAdminConnectionAsync(NewToken(), "b11-e2e-drain");
        await using var channel = await admin.CreateChannelAsync(cancellationToken: NewToken());
        while (true)
        {
            var fetched = await channel.BasicGetAsync(AgentMessagingTopology.ExecuteQueue, autoAck: true, NewToken());
            if (fetched is null)
            {
                break;
            }

            messages.Add(new WireCommand(
                fetched.BasicProperties.MessageId,
                Encoding.UTF8.GetString(fetched.Body.ToArray())));
        }

        return messages;
    }

    /// <summary>agent_svc rolüyle agent.run olayını gerçek broker'a yayınlar —
    /// python AgentEventPublisher'ın kablo zarfı (B5 sözleşmesi).</summary>
    private async Task<string> PublishAgentEventAsync(
        Guid runId, Guid conversationId, string messageType, long sequence,
        Dictionary<string, object?> payload)
    {
        var envelope = new Dictionary<string, object?>
        {
            ["message_id"] = Guid.NewGuid().ToString("D"),
            ["message_type"] = messageType,
            ["schema_version"] = 1,
            ["run_id"] = runId.ToString("D"),
            ["conversation_id"] = conversationId.ToString("D"),
            ["correlation_id"] = Guid.NewGuid().ToString("D"),
            ["occurred_at"] = DateTime.UtcNow.ToString("yyyy-MM-dd'T'HH:mm:ss'Z'"),
            ["producer"] = "agent-py",
            ["payload"] = payload,
        };
        var body = Encoding.UTF8.GetBytes(JsonSerializer.Serialize(envelope));
        var messageId = (string)envelope["message_id"]!;

        var settings = _fixture.AgentSettings();
        await using var connections = new RabbitMqConnectionManager(settings);
        await using var publisher = new RabbitMqAgentPublisher(connections, settings, ["blog.agent.events"]);
        await publisher.StartAsync(NewToken());
        var result = await publisher.PublishAsync(
            "blog.agent.events", $"{messageType}.v1", body, messageId,
            envelope["correlation_id"]!.ToString()!, messageType, NewToken());
        Assert.True(result.Confirmed, $"olay yayını confirm almadı: {result.Detail}");
        return messageId;
    }

    /// <summary>Gerçek AgentEventProjectionConsumer (B5/B9 kablolaması); koşul
    /// sağlanana dek olayları tüketir.</summary>
    private async Task ConsumeEventsUntilAsync(Func<Task<bool>> condition)
    {
        var services = new ServiceCollection();
        services.AddOptions();
        services.AddLogging();
        services.AddSingleton(_fixture.BackendSettings());
        services.AddSingleton<IRabbitMqConnectionManager, RabbitMqConnectionManager>();
        services.AddDbContext<AppDbContext>(options =>
            options.UseNpgsql(_fixture.TestConnectionString, npgsql =>
                npgsql.MigrationsAssembly(typeof(AppDbContext).Assembly.FullName)));
        services.AddScoped<IApplicationDbContext>(sp => sp.GetRequiredService<AppDbContext>());
        services.AddScoped<IUnitOfWork, UnitOfWork>();
        services.AddSingleton<IAgentRunNotifier, RecordingE2eNotifier>();
        services.AddSingleton(new AgentContractValidator());
        services.AddScoped<BlogApp.Core.Application.Features.AgentFeature.Collaboration.IAgentCollaborationStore,
            EfAgentCollaborationStore>();
        services.AddScoped<IAgentResultPresentationGuard, AgentResultPresentationGuard>();
        services.AddScoped<AgentRunEventProjectionHandler>();
        services.AddSingleton<AgentEventProjectionConsumer>();

        var provider = services.BuildServiceProvider();
        var consumer = provider.GetRequiredService<AgentEventProjectionConsumer>();
        await consumer.StartAsync(NewToken());
        try
        {
            var ok = await WaitForAsync(async () => await condition(), TimeSpan.FromSeconds(45));
            Assert.True(ok, "projection koşulu 45 sn içinde sağlanmadı");

            // Commit→ACK yarışı kapanışı (B5 projection commit'ten sonra ACK):
            // koşul sağlandığında son teslimin ACK'ı hâlâ yolda olabilir. ACK'siz
            // consumer durdurulursa mesaj kuyruğa geri döner ve kimse tüketmez —
            // bu yüzden durdurmadan ÖNCE kuyruk sakinleşir (ready=0 VE unacked=0;
            // passive declare ready saymadığından unacked yönetim API'sinden okunur).
            var quiesced = await WaitForAsync(async () =>
            {
                try
                {
                    var (ready, unacked) =
                        await _fixture.QueueCountsAsync(AgentMessagingTopology.BackendEventsQueue);
                    return ready == 0 && unacked == 0;
                }
                catch (Exception)
                {
                    return false; // yönetim API geçici hatası: yeniden yokla
                }
            }, TimeSpan.FromSeconds(15));
            Assert.True(quiesced, "olay kuyruğu tüketim sonrası sakinleşmedi (ready/unacked)");
        }
        finally
        {
            await consumer.StopAsync(NewToken());
            if (provider is IAsyncDisposable asyncDisposable)
            {
                await asyncDisposable.DisposeAsync();
            }
            else
            {
                provider.Dispose();
            }
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
                    "b11-broker-wait");
                return;
            }
            catch
            {
                await Task.Delay(1000);
            }
        }

        Assert.Fail("broker 2 dakikada ayakta gelmedi");
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

    private static async Task<bool> WaitForAsync(Func<Task<bool>> condition, TimeSpan timeout)
    {
        var deadline = DateTime.UtcNow + timeout;
        while (DateTime.UtcNow < deadline)
        {
            if (await condition())
            {
                return true;
            }

            await Task.Delay(250);
        }

        return await condition();
    }

    private async Task<string> OutboxMessageIdOfAsync(Guid runId)
    {
        await using var context = _fixture.CreateContext();
        return await context.OutboxMessages
            .Where(m => m.RunId == runId)
            .Select(m => m.MessageId)
            .SingleAsync();
    }

    private sealed record WireCommand(string? MessageId, string BodyUtf8);

    private sealed class E2eCurrentUser(Guid? userId) : ICurrentUserService
    {
        public Guid? UserId => userId;
        public string? UserName => "b11-e2e-user";
        public string? Email => null;
        public string? CorrelationId => null;
        public bool IsAuthenticated => true;
        public bool IsInRole(string role) => false;
    }

    private sealed class RecordingE2eNotifier : IAgentRunNotifier
    {
        public Task NotifyAsync(AgentRunNotification notification, CancellationToken cancellationToken = default) =>
            Task.CompletedTask;
    }

    private sealed class RelayHost(IServiceProvider provider) : IDisposable
    {
        public Task StartAsync(CancellationToken cancellationToken) =>
            provider.GetRequiredService<IHostedService>().StartAsync(cancellationToken);

        public Task StopAsync(CancellationToken cancellationToken) =>
            provider.GetRequiredService<IHostedService>().StopAsync(cancellationToken);

        public void Dispose()
        {
            if (provider is IAsyncDisposable asyncDisposable)
            {
                asyncDisposable.DisposeAsync().AsTask().GetAwaiter().GetResult();
            }
            else if (provider is IDisposable disposable)
            {
                disposable.Dispose();
            }
        }
    }
}
