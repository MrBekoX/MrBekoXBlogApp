namespace BlogApp.Presentation.Api.Health;

/// <summary>
/// B11 agent sağlık kontrollerinin eşikleri — appsettings "AgentHealth" section.
///
/// Plan (satır 561): "Liveness, broker bağlantı readiness ve outbox backlog
/// kontrollerini ayır." Bu ayrımın eşik tarafı buradadır; kontrol sınıfları
/// <see cref="AgentBrokerHealthCheck"/> ve <see cref="AgentOutboxBacklogHealthCheck"/>'tir.
///
/// K3 kuralı gereği broker erişilemezse uygulama KALKMAYA DEVAM EDER ve kabul
/// yolu DB outbox'ına yazar; bu yüzden broker kontrolü asla liveness'a ya da
/// ana /health/ready hazır-bulunurluğuna bağlanmaz — yalnız /health/agent altında
/// operatör sinyali olarak raporlanır. Eşikler ürün kararı değil operasyon
/// kararıdır: üretimde appsettings ile değiştirilir (sır içermez).
/// </summary>
public sealed class AgentHealthOptions
{
    public const string SectionName = "AgentHealth";

    /// <summary>Broker bağlantı denemesinin üst sınırı (saniye); kontrol isteği bloklamasın.</summary>
    public int BrokerConnectTimeoutSeconds { get; set; } = 5;

    /// <summary>Backlog bu sayıyı aşarsa Degraded (uyarı; kabul devam eder).</summary>
    public int OutboxWarnPendingCount { get; set; } = 50;

    /// <summary>Backlog bu sayıyı aşarsa Unhealthy (kabul sınırı B7 MaxActiveRunsTotal'dadır;
    /// bu eşik yalnız operatör sinyalidir).</summary>
    public int OutboxUnhealthyPendingCount { get; set; } = 500;

    /// <summary>En eski çözümlenmemiş outbox kaydı bu yaştan (dakika) yeniyse kayıp sayılmaz:
    /// relay'in normal poll/confirm pencerisi alarm üretmesin.</summary>
    public int OutboxGraceMinutes { get; set; } = 2;

    /// <summary>En eski çözümlenmemiş kayıt bu yaşı (dakika) aşarsa Degraded:
    /// "broker kapalıyken kabul edilen iş bekliyor" durumunun görünür karşılığı.</summary>
    public int OutboxWarnOldestMinutes { get; set; } = 5;

    /// <summary>En eski çözümlenmemiş kayıt bu yaşı (dakika) aşarsa Unhealthy:
    /// relay/topoloji sorununda operatör müdahalesi (DLQ/topoloji/rollback) beklenir.</summary>
    public int OutboxUnhealthyOldestMinutes { get; set; } = 30;
}
