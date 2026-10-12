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

        foreach (var spec in AgentMessageTypeRegistry.MessageTypes)
        {
            var covered = bindings.Any(b => b.Exchange == spec.Exchange && TopicMatches(b.RoutingKey, spec.RoutingKey));
            Assert.True(covered, $"{spec.MessageType} ({spec.RoutingKey}, {spec.Exchange}) için binding yok");
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
