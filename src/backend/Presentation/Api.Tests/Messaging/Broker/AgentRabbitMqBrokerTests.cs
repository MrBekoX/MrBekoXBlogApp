using System.Diagnostics;
using BlogApp.BuildingBlocks.Messaging;
using RabbitMQ.Client;
using RabbitMQ.Client.Events;
using Xunit;

namespace BlogApp.Presentation.Api.Tests.Messaging.Broker;

/// <summary>
/// B2 broker kabul ölçütleri, gerçek RabbitMQ 4.2 broker'ına karşı (docker compose):
/// topology tekrarlı kurulumda bozulmaz; bağlanmamış routing key fark edilir;
/// consumer yeniden bağlantı sonrası çalışır; yetki kapsamı broker'da uygulanır.
/// Python tarafı (tests/messaging_broker) aynı topolojiyi ve broker'ı paylaşır;
/// aynı argümanla çift taraflı declare PRECONDITION_FAILED üretmez (diller arası tutarlılık).
/// </summary>
public class AgentRabbitMqBrokerTests
{
    private static readonly string[] BackendPublisherExchanges =
        [AgentMessagingTopology.CommandsExchange, AgentMessagingTopology.ContentExchange];

    private static CancellationToken Token => new CancellationTokenSource(TimeSpan.FromMinutes(3)).Token;

    // ---------------------------------------------------------------- topology

    [Fact]
    public async Task TopologyInitializer_DeclaresIdempotently()
    {
        await using var initializer = new AgentTopologyInitializer(BrokerTestEnvironment.BackendSettings());

        await initializer.InitializeAsync(Token);
        await initializer.InitializeAsync(Token); // tekrarlı kurulum: PRECONDITION_FAILED olmamalı

        // pasif doğrulama: varlıklar mevcut; Python tarafının declare ettiği kuyruk da dahil
        var connections = new RabbitMqConnectionManager(BrokerTestEnvironment.BackendSettings());
        var connection = await connections.GetConnectionAsync(Token);
        await using var channel = await connection.CreateChannelAsync(cancellationToken: Token);
        foreach (var queue in new[]
                 {
                     AgentMessagingTopology.ExecuteQueue,
                     AgentMessagingTopology.ControlQueue,
                     AgentMessagingTopology.ContentQueue,
                     AgentMessagingTopology.BackendEventsQueue,
                 })
        {
            var ok = await channel.QueueDeclarePassiveAsync(queue, Token);
            Assert.NotNull(ok);
        }

        await connections.CloseAsync(Token);
        await connections.DisposeAsync();
    }

    [Fact]
    public async Task TopologyInitializer_ArgumentMismatch_IsRejectedWithoutBreakingTopology()
    {
        var settings = BrokerTestEnvironment.AdminSettings();
        var connections = new RabbitMqConnectionManager(settings);
        var connection = await connections.GetConnectionAsync(Token);
        var name = "zz.dotnet.mismatch.q";

        await using (var channel = await connection.CreateChannelAsync(cancellationToken: Token))
        {
            await channel.QueueDeclareAsync(name, durable: true, exclusive: false, autoDelete: false, cancellationToken: Token);
            await using var second = await connection.CreateChannelAsync(cancellationToken: Token);
            await Assert.ThrowsAnyAsync<Exception>(() => second.QueueDeclareAsync(
                name, durable: true, exclusive: false, autoDelete: false,
                arguments: new Dictionary<string, object?> { ["x-message-ttl"] = 1000 }, cancellationToken: Token));
        }

        // kanal 406 ile kapandı; temizlik taze kanalla
        await using (var cleanup = await connection.CreateChannelAsync(cancellationToken: Token))
        {
            await cleanup.QueueDeleteAsync(name, cancellationToken: Token);
        }

        await connections.CloseAsync(Token);
        await connections.DisposeAsync();
    }

    // ---------------------------------------------------------------- publisher

    [Fact]
    public async Task Publisher_PublishesPersistentMessageWithConfirmAndAmqpProperties()
    {
        var connections = new RabbitMqConnectionManager(BrokerTestEnvironment.BackendSettings());
        await using var publisher = new RabbitMqAgentPublisher(connections, BrokerTestEnvironment.BackendSettings(), BackendPublisherExchanges);
        await publisher.StartAsync(Token);

        var messageId = Guid.NewGuid().ToString("N");
        var correlationId = Guid.NewGuid().ToString("N");
        var body = """{"probe":"dotnet-confirm"}"""u8.ToArray();
        var result = await publisher.PublishAsync(
            AgentMessagingTopology.CommandsExchange,
            "agent.execute.requested.v1",
            body,
            messageId,
            correlationId,
            "agent.execute.requested",
            Token);

        Assert.True(result.Confirmed);
        Assert.False(result.Returned);

        // broker'a düşen mesajı admin bağlantısıyla doğrula
        await using var admin = await BrokerTestEnvironment.OpenAdminConnectionAsync(Token);
        await using var channel = await admin.CreateChannelAsync(cancellationToken: Token);
        var fetched = await channel.BasicGetAsync(AgentMessagingTopology.ExecuteQueue, autoAck: true, Token);
        Assert.NotNull(fetched);
        Assert.Equal(messageId, fetched!.BasicProperties.MessageId);
        Assert.Equal(correlationId, fetched.BasicProperties.CorrelationId);
        Assert.Equal("agent.execute.requested", fetched.BasicProperties.Type);
        Assert.Equal("application/json", fetched.BasicProperties.ContentType);
        Assert.Equal(DeliveryModes.Persistent, fetched.BasicProperties.DeliveryMode);
        Assert.Equal(body, fetched.Body.ToArray());

        await connections.CloseAsync(Token);
        await connections.DisposeAsync();
    }

    [Fact]
    public async Task Publisher_MandatoryUnroutableRoutingKey_IsReportedNotConfirmed()
    {
        var connections = new RabbitMqConnectionManager(BrokerTestEnvironment.BackendSettings());
        await using var publisher = new RabbitMqAgentPublisher(connections, BrokerTestEnvironment.BackendSettings(), BackendPublisherExchanges);
        await publisher.StartAsync(Token);

        var result = await publisher.PublishAsync(
            AgentMessagingTopology.CommandsExchange,
            "zz.b2.dotnet.unroutable.v1", // commands binding'leriyle eşleşmez
            """{"probe":"unroutable"}"""u8.ToArray(),
            Guid.NewGuid().ToString("N"),
            Guid.NewGuid().ToString("N"),
            "agent.execute.requested",
            Token);

        Assert.True(result.Returned, "bağlanmamış routing key başarı sayılamaz");
        Assert.False(result.Confirmed);
        Assert.Contains("unroutable", result.Detail);

        await connections.CloseAsync(Token);
        await connections.DisposeAsync();
    }

    [Fact]
    public async Task Publisher_RejectsBodyOverContractLimit_BeforePublish()
    {
        var settings = BrokerTestEnvironment.BackendSettings();
        var connections = new RabbitMqConnectionManager(settings);
        await using var publisher = new RabbitMqAgentPublisher(connections, settings, BackendPublisherExchanges);
        await publisher.StartAsync(Token);

        await Assert.ThrowsAsync<ArgumentException>(() => publisher.PublishAsync(
            AgentMessagingTopology.CommandsExchange,
            "agent.execute.requested.v1",
            new byte[settings.MaxPublishBytes + 1],
            cancellationToken: Token));

        await connections.CloseAsync(Token);
        await connections.DisposeAsync();
    }

    // ---------------------------------------------------------------- consumer

    [Fact]
    public async Task Consumer_ReceivesAcksAndRespectsPrefetch()
    {
        var settings = BrokerTestEnvironment.BackendSettings();
        settings.ConsumerPrefetchCount = 2;
        var connections = new RabbitMqConnectionManager(settings);

        var handled = new List<byte[]>();
        var maxInFlight = 0;
        var inFlight = 0;
        var semaphore = new SemaphoreSlim(1, 1);

        var consumer = new TestConsumer(connections, settings, AgentMessagingTopology.BackendEventsQueue,
            (_, _, body, _) =>
            {
                semaphore.Wait();
                try
                {
                    inFlight++;
                    maxInFlight = Math.Max(maxInFlight, inFlight);
                }
                finally
                {
                    semaphore.Release();
                }
                Thread.Sleep(150);
                lock (handled) { handled.Add(body); }
                semaphore.Wait();
                try { inFlight--; } finally { semaphore.Release(); }
                return Task.CompletedTask;
            });

        await consumer.StartAsync(Token);

        await using (var admin = await BrokerTestEnvironment.OpenAdminConnectionAsync(Token))
        await using (var channel = await admin.CreateChannelAsync(cancellationToken: Token))
        {
            var properties = new BasicProperties { DeliveryMode = DeliveryModes.Persistent, ContentType = "application/json" };
            for (var i = 0; i < 4; i++)
            {
                await channel.BasicPublishAsync(
                    AgentMessagingTopology.EventsExchange,
                    "agent.run.completed.v1",
                    mandatory: true,
                    properties,
                    System.Text.Encoding.UTF8.GetBytes($"{{\"n\":{i}}}"),
                    Token);
            }
        }

        var deadline = DateTime.UtcNow.AddSeconds(30);
        while (CountOf(handled) < 4 && DateTime.UtcNow < deadline)
        {
            await Task.Delay(100, Token);
        }

        await consumer.StopAsync(Token);
        await connections.CloseAsync(Token);
        await connections.DisposeAsync();

        Assert.Equal(4, CountOf(handled));
        Assert.InRange(maxInFlight, 1, settings.ConsumerPrefetchCount);
    }

    [Fact]
    public async Task Consumer_HandlerFailure_DeadLettersWithoutRequeueLoop()
    {
        var settings = BrokerTestEnvironment.BackendSettings();
        var connections = new RabbitMqConnectionManager(settings);

        // önceki testlerden kalma mesajları temizle (consumer testleri yalıtılmalı)
        await PurgeAsync(AgentMessagingTopology.BackendEventsQueue,
            AgentMessagingTopology.DeadLetterQueueFor(AgentMessagingTopology.BackendEventsQueue));

        var attempts = 0;
        var consumer = new TestConsumer(connections, settings, AgentMessagingTopology.BackendEventsQueue,
            (_, _, _, _) =>
            {
                Interlocked.Increment(ref attempts);
                throw new InvalidOperationException("bilinçli test hatası");
            });

        await consumer.StartAsync(Token);

        await using (var admin = await BrokerTestEnvironment.OpenAdminConnectionAsync(Token))
        await using (var channel = await admin.CreateChannelAsync(cancellationToken: Token))
        {
            await channel.BasicPublishAsync(
                AgentMessagingTopology.EventsExchange,
                "agent.run.completed.v1",
                mandatory: true,
                new BasicProperties { DeliveryMode = DeliveryModes.Persistent },
                """{"probe":"dead"}"""u8.ToArray(),
                Token);
        }

        // DLQ'ya düşmesini bekle
        byte[]? deadBody = null;
        string? deadRoutingKey = null;
        var deadline = DateTime.UtcNow.AddSeconds(30);
        await using (var admin = await BrokerTestEnvironment.OpenAdminConnectionAsync(Token))
        await using (var channel = await admin.CreateChannelAsync(cancellationToken: Token))
        {
            while (DateTime.UtcNow < deadline)
            {
                var fetched = await channel.BasicGetAsync(
                    AgentMessagingTopology.DeadLetterQueueFor(AgentMessagingTopology.BackendEventsQueue),
                    autoAck: true, Token);
                if (fetched is not null)
                {
                    deadBody = fetched.Body.ToArray();
                    deadRoutingKey = fetched.RoutingKey;
                    break;
                }

                await Task.Delay(300, Token);
            }
        }

        await consumer.StopAsync(Token);
        await connections.CloseAsync(Token);
        await connections.DisposeAsync();

        Assert.NotNull(deadBody);
        Assert.Equal("agent.run.completed.v1", deadRoutingKey); // rk korunur, hedef DLQ'ya düşer
        Assert.Equal(1, attempts); // requeue döngüsü yok
    }

    [Fact]
    public async Task Consumer_RecoversAfterBrokerForcedConnectionClosure()
    {
        // gerçek kesinti: broker tüm bağlantıları zorla kapatır; otomatik recovery devreye girer
        KillAllBrokerConnections();

        var settings = BrokerTestEnvironment.BackendSettings();
        settings.NetworkRecoveryIntervalSeconds = 2;
        var connections = new RabbitMqConnectionManager(settings);

        await PurgeAsync(AgentMessagingTopology.BackendEventsQueue,
            AgentMessagingTopology.DeadLetterQueueFor(AgentMessagingTopology.BackendEventsQueue));

        var handled = new List<string>();
        var consumer = new TestConsumer(connections, settings, AgentMessagingTopology.BackendEventsQueue,
            (_, routingKey, body, _) =>
            {
                lock (handled) { handled.Add(routingKey); }
                return Task.CompletedTask;
            });

        await consumer.StartAsync(Token);
        KillAllBrokerConnections(); // tüketim başladıktan sonra kesinti

        await using (var admin = await BrokerTestEnvironment.OpenAdminConnectionAsync(Token, "dotnet-recovery-publisher"))
        await using (var channel = await admin.CreateChannelAsync(cancellationToken: Token))
        {
            // recovery dönemi için bekle sonra yayınla; consumer yeniden bağlanınca almalı
            await Task.Delay(TimeSpan.FromSeconds(5), Token);
            await channel.BasicPublishAsync(
                AgentMessagingTopology.EventsExchange,
                "agent.run.completed.v1",
                mandatory: true,
                new BasicProperties { DeliveryMode = DeliveryModes.Persistent },
                """{"probe":"after-kill"}"""u8.ToArray(),
                Token);
        }

        var deadline = DateTime.UtcNow.AddSeconds(60);
        lock (handled)
        {
            while (handled.Count == 0 && DateTime.UtcNow < deadline)
            {
                Monitor.Wait(handled, 250);
            }
        }

        await consumer.StopAsync(Token);
        await connections.CloseAsync(Token);
        await connections.DisposeAsync();

        lock (handled)
        {
            Assert.NotEmpty(handled); // yeniden bağlantı sonrası consumer çalışır
        }
    }

    // ---------------------------------------------------------------- yardımcılar

    private static int CountOf(List<byte[]> list)
    {
        lock (list) { return list.Count; }
    }

    /// <summary>Verilen kuyrukları admin bağlantısıyla boşaltır (test yalıtımı).</summary>
    private static async Task PurgeAsync(params string[] queues)
    {
        await using var admin = await BrokerTestEnvironment.OpenAdminConnectionAsync(Token, "dotnet-tests-purge");
        await using var channel = await admin.CreateChannelAsync(cancellationToken: Token);
        foreach (var queue in queues)
        {
            await channel.QueuePurgeAsync(queue, Token);
        }
    }

    private static void KillAllBrokerConnections()
    {
        var psi = new ProcessStartInfo
        {
            FileName = "docker",
            Arguments = $"exec {BrokerTestEnvironment.RabbitMqContainer} rabbitmqctl close_all_connections -q \"broker-interruption-test\"",
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            UseShellExecute = false,
        };
        using var process = Process.Start(psi)!;
        process.WaitForExit(60_000);
        Assert.True(process.ExitCode == 0, $"rabbitmqctl close_all_connections başarısız: {process.StandardError.ReadToEnd()}");
    }

    /// <summary>Test amaçlı somut consumer; handler temsilcisi test gövdesinden verilir.</summary>
    private sealed class TestConsumer : RabbitMqAgentConsumer
    {
        private readonly Func<string, string, byte[], BasicDeliverEventArgs, Task> _handler;

        public TestConsumer(
            IRabbitMqConnectionManager connections,
            RabbitMqSettings settings,
            string queueName,
            Func<string, string, byte[], BasicDeliverEventArgs, Task> handler)
            : base(connections, settings, queueName)
        {
            _handler = handler;
        }

        protected override Task HandleAsync(
            string exchange,
            string routingKey,
            byte[] body,
            BasicDeliverEventArgs delivery,
            CancellationToken cancellationToken)
        {
            return _handler(exchange, routingKey, body, delivery);
        }
    }
}
