namespace BlogApp.BuildingBlocks.Messaging;

/// <summary>Bir broker kuyruğunun declare planı; arguments DLX/TTL gibi broker argümanlarını taşır.</summary>
public sealed record QueueSpec(string Name, bool Durable, IDictionary<string, object?> Arguments);

/// <summary>Bir kuyruk-exchange bağlama planı.</summary>
public sealed record BindingSpec(string Queue, string Exchange, string RoutingKey);

/// <summary>
/// Plan B2 topolojisi (satır 41-56 diyagram + satır 219-233 B1 yön/routing tablosu):
/// 3 topic exchange, 4 ana kuyruk, per-kuyruk DLQ ve hedefe özel retry kuyrukları.
/// ``content.project.changed.v1`` binding'i B1 registry'sinde tanımlı türün routable
/// olması için eklenmiştir (bağlı olmayan routing key kuyruğa düşmez).
///
/// Argüman modeli: ana kuyruklar ``x-dead-letter-exchange=blog.agent.dead`` ile doğar;
/// ``x-dead-letter-routing-key`` set edilmediği için orijinal routing key korunur ve
/// mesaj hedef DLQ'ya düşer. Retry kuyruğu TTL sonrası mesajı orijinal exchange'e,
/// korunan routing key ile geri dead-letter'lar (hedefe özel retry).
/// Tek declarer backend'dir (K3); aynı argümanla tekrarlı declare bozulmaz.
/// </summary>
public static class AgentMessagingTopology
{
    public const string CommandsExchange = "blog.agent.commands";
    public const string EventsExchange = "blog.agent.events";
    public const string ContentExchange = "blog.content.events";
    public const string DeadLetterExchange = "blog.agent.dead";

    public const string ExecuteQueue = "agent.execute.q";
    public const string ControlQueue = "agent.control.q";
    public const string ContentQueue = "agent.content.q";
    public const string BackendEventsQueue = "backend.agent.events.q";

    /// <summary>Hedefe özel retry kademeleri (B7 başlangıç önerisi: 10s/30s/2dk).</summary>
    public static readonly int[] DefaultRetryTierSeconds = [10, 30, 120];

    private static readonly (string Queue, string[] RoutingKeys, string OriginExchange)[] Targets =
    [
        (ExecuteQueue, ["agent.execute.requested.v1"], CommandsExchange),
        (ControlQueue, ["agent.cancel.requested.v1", "agent.resume.requested.v1", "agent.action.result.v1"], CommandsExchange),
        (ContentQueue, ["content.article.changed.v1", "content.sync.#", "content.profile.changed.v1", "content.project.changed.v1"], ContentExchange),
        (BackendEventsQueue, ["agent.run.#", "agent.action.#"], EventsExchange),
    ];

    public static string DeadLetterQueueFor(string queue) => $"{queue}.dlq";

    public static string RetryQueueFor(string queue, int tierSeconds) => $"{queue}.retry.{tierSeconds}s.q";

    public static string RetryExchangeFor(int tierSeconds) => $"blog.agent.retry.{tierSeconds}s";

    /// <summary>Exchange declare planı (tümü durable topic).</summary>
    public static IReadOnlyList<string> Exchanges(int[] retryTierSeconds)
    {
        var exchanges = new List<string>
        {
            CommandsExchange,
            EventsExchange,
            ContentExchange,
            DeadLetterExchange,
        };
        exchanges.AddRange(retryTierSeconds.Select(RetryExchangeFor));
        return exchanges;
    }

    /// <summary>Kuyruk declare planı: ana kuyruklar (DLX'li), DLQ'lar, retry kuyrukları (TTL + geri DLX).</summary>
    public static IReadOnlyList<QueueSpec> Queues(int[] retryTierSeconds)
    {
        var queues = new List<QueueSpec>();
        foreach (var (queue, _, originExchange) in Targets)
        {
            queues.Add(new QueueSpec(
                queue,
                Durable: true,
                new Dictionary<string, object?> { ["x-dead-letter-exchange"] = DeadLetterExchange }));
            queues.Add(new QueueSpec(DeadLetterQueueFor(queue), Durable: true, new Dictionary<string, object?>()));
        }

        foreach (var tier in retryTierSeconds)
        {
            foreach (var (queue, _, originExchange) in Targets)
            {
                queues.Add(new QueueSpec(
                    RetryQueueFor(queue, tier),
                    Durable: true,
                    new Dictionary<string, object?>
                    {
                        ["x-message-ttl"] = tier * 1000,
                        ["x-dead-letter-exchange"] = originExchange,
                    }));
            }
        }

        return queues;
    }

    /// <summary>Binding planı: ana kuyruk + DLQ (aynı routing key'ler) + retry kuyrukları (tier exchange'i).</summary>
    public static IReadOnlyList<BindingSpec> Bindings(int[] retryTierSeconds)
    {
        var bindings = new List<BindingSpec>();
        foreach (var (queue, routingKeys, originExchange) in Targets)
        {
            foreach (var routingKey in routingKeys)
            {
                bindings.Add(new BindingSpec(queue, originExchange, routingKey));
                bindings.Add(new BindingSpec(DeadLetterQueueFor(queue), DeadLetterExchange, routingKey));
            }
        }

        foreach (var tier in retryTierSeconds)
        {
            foreach (var (queue, routingKeys, _) in Targets)
            {
                foreach (var routingKey in routingKeys)
                {
                    bindings.Add(new BindingSpec(RetryQueueFor(queue, tier), RetryExchangeFor(tier), routingKey));
                }
            }
        }

        return bindings;
    }
}
