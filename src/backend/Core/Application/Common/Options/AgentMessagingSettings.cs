namespace BlogApp.Core.Application.Common.Options;

/// <summary>
/// Agent mesajlaşma sözleşme sınırları — appsettings.json "AgentMessaging" section (B0 K7).
/// Yayın ve tüketim tarafları payload üst sınırını iki uçta da doğrular.
/// </summary>
public sealed class AgentMessagingSettings
{
    public const string SectionName = "AgentMessaging";

    /// <summary>Komut/olay gövdesi üst sınırı; plan B1 ve B0 K7 kararı: 256 KiB.</summary>
    public int MaxPayloadBytes { get; set; } = 262_144;

    /// <summary>Bu servisin envelope.producer kimliği (B0 §4 üretici enum'u).</summary>
    public string ProducerName { get; set; } = "backend-net";
}
