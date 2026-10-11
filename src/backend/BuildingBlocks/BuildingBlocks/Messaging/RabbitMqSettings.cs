namespace BlogApp.BuildingBlocks.Messaging;

/// <summary>
/// RabbitMQ broker bağlantı ve tüketim ayarları — appsettings "RabbitMq" section (B2).
/// Geliştirme/üretim ayrımı vhost ile yapılır (plan satır 253); exchange/kuyruk adları
/// donmuş B1 sözleşmesinden ve plan topolojisinden gelir, yapılandırmaya bağlı değildir.
/// </summary>
public sealed class RabbitMqSettings
{
    public const string SectionName = "RabbitMq";

    public string Host { get; set; } = "localhost";

    public int Port { get; set; } = 5672;

    public string UserName { get; set; } = "guest";

    public string Password { get; set; } = "guest";

    /// <summary>Geliştirme/üretim ayrımı vhost üzerinden yapılır (plan B2).</summary>
    public string VirtualHost { get; set; } = "/";

    /// <summary>Broker tarafında bağlantıyı ayırt eden istemci adı.</summary>
    public string ClientProvidedName { get; set; } = "backend-net";

    /// <summary>AMQP heartbeat (saniye); uzun ömürlü bağlantıda ölü bağlantı tespiti.</summary>
    public int RequestedHeartbeatSeconds { get; set; } = 30;

    /// <summary>Bağlantı koptuktan sonra otomatik recovery deneme aralığı (saniye).</summary>
    public int NetworkRecoveryIntervalSeconds { get; set; } = 10;

    /// <summary>Consumer başına sınırlı prefetch (plan: sınırlı prefetch ve eşzamanlı tüketim).</summary>
    public int ConsumerPrefetchCount { get; set; } = 16;

    /// <summary>
    /// Topology declarer kimliği (opsiyonel; boşsa UserName/Password kullanılır).
    /// RabbitMQ 4.2 ölçümü: x-dead-letter-exchange'li kuyruğun yaratımı declarer'dan
    /// o kuyruk kaynağına read ve DLX exchange'ine write izni ister. Uygulama servis
    /// kullanıcısının (ör. backend_svc) events exchange'ine write yetkisi OLMAMALI
    /// (yetkisiz yayın engeli); bu yüzden declarer ayrı bir operasyonel kimliktir ve
    /// uygulama mesajı yayınlamak için kullanılmaz (K3: tek declarer backend dağıtımı).
    /// </summary>
    public string? DeclarerUserName { get; set; }

    public string? DeclarerPassword { get; set; }

    /// <summary>Payload üst sınırı (bayt); B1 sözleşmesi MaxPayloadBytes ile ayna testiyle eşlenir.</summary>
    public int MaxPublishBytes { get; set; } = 262_144;

    /// <summary>Hedefe özel retry kuyruğu kademeleri (saniye); B7'nin değerlendirme önerisi.</summary>
    public int[] RetryTierSeconds { get; set; } = [10, 30, 120];
}
