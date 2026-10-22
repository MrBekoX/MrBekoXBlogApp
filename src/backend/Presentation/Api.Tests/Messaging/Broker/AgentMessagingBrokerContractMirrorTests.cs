using BlogApp.Core.Application.Common.Messaging;
using BlogApp.Core.Application.Common.Options;
using BlogApp.BuildingBlocks.Messaging;
using Xunit;

namespace BlogApp.Presentation.Api.Tests.Messaging.Broker;

/// <summary>
/// B2 ayna testleri: BuildingBlocks topoloji sabitleri donmuş B1 sözleşme kaydıyla ve
/// Core tarafındaki registry ile aynıdır; BuildingBlocks payload üst sınırı B1
/// MaxPayloadBytes ve contract.json üst sınırıyla eşittir. BuildingBlocks Core'a
/// bağımlı olmadığından bu eşitlik ancak testle sabitlenir.
/// </summary>
public class AgentMessagingBrokerContractMirrorTests
{
    [Fact]
    public void TopologyExchangeNames_MirrorB1Registry()
    {
        Assert.Equal(AgentMessageTypeRegistry.CommandsExchange, AgentMessagingTopology.CommandsExchange);
        Assert.Equal(AgentMessageTypeRegistry.EventsExchange, AgentMessagingTopology.EventsExchange);
        Assert.Equal(AgentMessageTypeRegistry.ContentExchange, AgentMessagingTopology.ContentExchange);
    }

    [Fact]
    public void PayloadLimit_MirrorsB1ContractConstants()
    {
        Assert.Equal(262_144, AgentMessagingSettings_ContractDefault());
        Assert.Equal(new AgentMessagingSettings().MaxPayloadBytes, new RabbitMqSettings().MaxPublishBytes);
    }

    [Fact]
    public void RoutingKeysOfBindings_CoverEveryB1RoutingKey()
    {
        // B1 registry'sindeki her routing key, ana kuyruk binding'lerinde karşılığını bulur;
        // bağlı olmayan bir sözleşme türü broker'da unroutable olurdu. AMQP topic eşleşmesi
        // (# = çok sözcük, * = tek sözcük) baz alınır: content.sync.# content.sync.batch.v1'i kapsar.
        var bindings = AgentMessagingTopology.Bindings(AgentMessagingTopology.DefaultRetryTierSeconds)
            .Where(b => !b.Queue.Contains("retry", StringComparison.Ordinal) && !b.Queue.EndsWith(".dlq", StringComparison.Ordinal))
            .Select(b => (b.Exchange, b.RoutingKey))
            .ToList();

        foreach (var spec in AgentMessageTypeRegistry.AllMessageTypes)
        {
            var covered = bindings.Any(b => b.Exchange == spec.Exchange && TopicMatches(b.RoutingKey, spec.RoutingKey));
            Assert.True(covered, $"v{spec.SchemaVersion} {spec.MessageType} ({spec.RoutingKey}, {spec.Exchange}) için binding yok");
        }
    }

    [Fact]
    public void CommandRoutingKeys_AreIsolatedPerWireVersion()
    {
        // K4 broker izolasyonu: her backend→agent komut routing key'i TAM OLARAK bir ana kuyruğa
        // bağlıdır; v1 komutları v1 kuyruklarına, v2 komutları yalnız *.v2.q kuyruklarına gider
        // (eski worker v2 komutunu hiç görmez). Liste BuildingBlocks'ta literal, kaynak ise
        // Core registry'si: bu test ikisini eşler.
        var mainQueues = AgentMessagingTopology.MainQueueRoutingKeys;
        var mainBindings = AgentMessagingTopology.Bindings(AgentMessagingTopology.DefaultRetryTierSeconds)
            .Where(b => mainQueues.ContainsKey(b.Queue))
            .ToList();
        foreach (var spec in AgentMessageTypeRegistry.AllMessageTypes
                     .Where(s => s.Direction == AgentMessageDirection.BackendToAgent && s.Exchange == AgentMessageTypeRegistry.CommandsExchange))
        {
            var boundQueues = mainBindings
                .Where(b => b.Exchange == spec.Exchange && TopicMatches(b.RoutingKey, spec.RoutingKey))
                .Select(b => b.Queue)
                .Distinct()
                .ToList();
            var queue = Assert.Single(boundQueues);

            var expected = (spec.SchemaVersion, spec.MessageType) switch
            {
                (1, AgentMessageTypes.ExecutionRequested) => AgentMessagingTopology.ExecuteQueue,
                (1, _) => AgentMessagingTopology.ControlQueue,
                (2, AgentMessageTypes.ExecutionRequested) => AgentMessagingTopology.ExecuteQueueV2,
                (2, _) => AgentMessagingTopology.ControlQueueV2,
                _ => throw new InvalidOperationException($"beklenmeyen sürüm {spec.SchemaVersion}"),
            };
            Assert.Equal(expected, queue);
        }

        // v2 kuyruklarına v1 anahtarı bağlanmaz (ters yön izolasyonu).
        Assert.All(mainQueues[AgentMessagingTopology.ExecuteQueueV2].Concat(mainQueues[AgentMessagingTopology.ControlQueueV2]),
            key => Assert.EndsWith(".v2", key));
    }

    [Fact]
    public void V2Queues_HaveDeadLetterAndRetryPlans_LikeV1()
    {
        var queues = AgentMessagingTopology.Queues(AgentMessagingTopology.DefaultRetryTierSeconds).ToDictionary(q => q.Name);
        foreach (var queue in (string[])[AgentMessagingTopology.ExecuteQueueV2, AgentMessagingTopology.ControlQueueV2])
        {
            Assert.True(queues[queue].Durable);
            Assert.Equal(AgentMessagingTopology.DeadLetterExchange, queues[queue].Arguments["x-dead-letter-exchange"]);
            Assert.True(queues.ContainsKey(AgentMessagingTopology.DeadLetterQueueFor(queue)));
            foreach (var tier in AgentMessagingTopology.DefaultRetryTierSeconds)
            {
                Assert.True(queues.ContainsKey(AgentMessagingTopology.RetryQueueFor(queue, tier)));
            }
        }
    }

    /// <summary>AMQP topic pattern eşleşmesi (# çok sözcük, * tek sözcük).</summary>
    private static bool TopicMatches(string pattern, string routingKey)
    {
        var patternParts = pattern.Split('.');
        var keyParts = routingKey.Split('.');
        return Matches(patternParts, keyParts);
    }

    private static bool Matches(string[] pattern, string[] key)
    {
        var p = 0;
        var k = 0;
        while (p < pattern.Length && k < key.Length)
        {
            if (pattern[p] == "#")
            {
                // # sıfır veya daha çok sözcük; desen sonundaysa kesin eşleşme
                if (p == pattern.Length - 1) { return true; }
                for (var skip = k; skip <= key.Length; skip++)
                {
                    if (Matches(pattern[(p + 1)..], key[skip..])) { return true; }
                }
                return false;
            }

            if (pattern[p] != "*" && !string.Equals(pattern[p], key[k], StringComparison.Ordinal))
            {
                return false;
            }
            p++;
            k++;
        }

        if (p < pattern.Length)
        {
            // kalan desen yalnızca #'ler ise eşleşir
            return pattern[p..].All(part => part == "#");
        }
        return k == key.Length;
    }

    [Fact]
    public void DefaultRetryTiers_MatchB7Proposal()
    {
        Assert.Equal(new[] { 10, 30, 120 }, new RabbitMqSettings().RetryTierSeconds);
    }

    private static int AgentMessagingSettings_ContractDefault() => new AgentMessagingSettings().MaxPayloadBytes;
}
