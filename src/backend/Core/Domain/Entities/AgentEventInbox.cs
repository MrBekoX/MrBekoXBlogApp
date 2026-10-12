namespace BlogApp.Core.Domain.Entities;

/// <summary>
/// Backend olay tüketiminde mesaj bazlı idempotency kaydı (B5, plan B5 backend listesi:
/// "olay doğrulaması, inbox kaydı ve run projection değişikliği tek transaction").
/// PK (ConsumerName, MessageId): bir tüketici için bir broker mesajı en fazla bir
/// satır doğurur; commit edilmiş satır varsa tekrar teslim aynı projection'a
/// YENİDEN UYGULANMAZ. Satır projection değişikliğiyle AYNI transaction'da yazılır;
/// commit öncesi çökmede satır da projection da geri alınır (tekrar teslim temiz işler).
/// Bilinmeyen run_id sınırlı politikası: satır ``quarantined`` durumuyla kalıcı
/// yazılır ve mesaj ACK'lanır (sonsuz retry/DLQ döngüsü kurulmaz; B7 genişletebilir).
/// bileşik PK gerektirdiğinden audit taban sınıflarından bağımsız düz entity'dir.
/// </summary>
public class AgentEventInbox
{
    /// <summary>Tüketici hizmeti kimliği (ör. "backend-agent-events"); consumer kapsamlı tekillik.</summary>
    public string ConsumerName { get; set; } = string.Empty;

    /// <summary>Zarf message_id (kanonik UUID); PK'nin ikinci bileşeni.</summary>
    public Guid MessageId { get; set; }

    /// <summary>agent.run.* / agent.action.* tür adı.</summary>
    public string MessageType { get; set; } = string.Empty;

    /// <summary>Olayın ait olduğu run; bilinmeyen run'da da kayıt bırakmak için nullable.</summary>
    public Guid? RunId { get; set; }

    /// <summary>Payload event_sequence; sıra gerilemesi kaydının okunabilirliği için.</summary>
    public long EventSequence { get; set; }

    /// <summary>applied | stale | quarantined.</summary>
    public string Status { get; set; } = string.Empty;

    /// <summary>Yoksayma/karantina gerekçesi (uygulanan olayda boş).</summary>
    public string? Detail { get; set; }

    /// <summary>Kayittaştırma anı (tekrar teslimde güncellenmez).</summary>
    public DateTime CreatedAt { get; set; }
}
