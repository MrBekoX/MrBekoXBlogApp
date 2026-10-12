using System.Text.Json.Serialization;

namespace BlogApp.Core.Application.Common.Messaging;

/// <summary>
/// Commit edilmiş projection'ın istemci bildirimi (B5, plan: "commit edilmiş projection
/// üzerinden UI bildirimi üret"). Yalnız projection'a UYGULANMIŞ olaylar bildirilir;
/// duplicate/stale/quarantined olaylar bildiri üretmez. Payload ResultJson yalnız
/// terminal olaylarda doludur (tam sonuç snapshot'ı).
/// </summary>
public sealed record AgentRunNotification
{
    [JsonPropertyName("run_id")]
    public required string RunId { get; init; }

    [JsonPropertyName("message_id")]
    public required string MessageId { get; init; }

    /// <summary>Tür adı (agent.run.progressed, agent.run.completed, ...).</summary>
    [JsonPropertyName("message_type")]
    public required string MessageType { get; init; }

    [JsonPropertyName("status")]
    public required string Status { get; init; }

    [JsonPropertyName("event_sequence")]
    public required long EventSequence { get; init; }

    /// <summary>Progress olaylarında payload message alanı; diğer olaylarda boş.</summary>
    [JsonPropertyName("message")]
    public string Message { get; init; } = string.Empty;

    [JsonPropertyName("occurred_at")]
    public required string OccurredAt { get; init; }

    /// <summary>Terminal snapshot JSON'u (yalnız terminal olaylarda).</summary>
    [JsonIgnore]
    public string? ResultJson { get; init; }
}

/// <summary>
/// Projection commit'i SONRASından UI bildirimini taşıyan soyutlama (B5). Hub türü
/// Presentation'da olduğundan Application arayüzü konuşur; Presentation SignalR
/// implementasyonunu kaydeder, Infrastructure tüketir. Bildirim hedefe ulaşmazsa
/// projection commit'i geri alınmaz: uygulama "SignalR gönderildi bilgisini kullanıcı
/// okudu garantisi sayma" kuralı gereği best-effort'tur (kalıcı tamamlama GET/replay,
/// B10).
/// </summary>
public interface IAgentRunNotifier
{
    Task NotifyAsync(AgentRunNotification notification, CancellationToken cancellationToken = default);
}
