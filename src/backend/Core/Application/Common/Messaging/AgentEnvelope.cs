using System.Text.Json;
using System.Text.Json.Serialization;

namespace BlogApp.Core.Application.Common.Messaging;

/// <summary>
/// B1 zarf sözleşmesi (plan satır 183-196 + delivery_attempt uzantısı).
/// Zorunlu alanlar: message_id, message_type, schema_version, correlation_id, occurred_at, producer, payload.
/// Zamanlar UTC ISO 8601; kimlikler kanonik UUID. Opsiyonel alanlarda null taşınmaz, alan çıkarılır.
/// </summary>
public sealed record AgentEnvelope
{
    [JsonPropertyName("message_id")]
    public required string MessageId { get; init; }

    [JsonPropertyName("message_type")]
    public required string MessageType { get; init; }

    [JsonPropertyName("schema_version")]
    public required int SchemaVersion { get; init; }

    [JsonPropertyName("run_id")]
    public string? RunId { get; init; }

    [JsonPropertyName("conversation_id")]
    public string? ConversationId { get; init; }

    [JsonPropertyName("correlation_id")]
    public required string CorrelationId { get; init; }

    [JsonPropertyName("causation_id")]
    public string? CausationId { get; init; }

    [JsonPropertyName("occurred_at")]
    public required string OccurredAt { get; init; }

    [JsonPropertyName("deadline_at")]
    public string? DeadlineAt { get; init; }

    [JsonPropertyName("producer")]
    public required string Producer { get; init; }

    [JsonPropertyName("trace_context")]
    public string? TraceContext { get; init; }

    /// <summary>Transport tekrar yayını sayacı (ilk yayında 0); agent yürütme denemesi payload'taki
    /// execution_attempt'tir — iki alan bilinçli olarak ayrıdır (plan satır 237).</summary>
    [JsonPropertyName("delivery_attempt")]
    public int DeliveryAttempt { get; init; }

    [JsonPropertyName("payload")]
    public required JsonElement Payload { get; init; }
}
