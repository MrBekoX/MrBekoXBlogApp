namespace BlogApp.Core.Domain.Enums;

/// <summary>
/// Backend'in AgentRun kaydının durumu. B3'te tek değer vardır: kabul.
/// Plan (02-rabbitmq-haberlesme-plani.md satır 305) kabul durumu ile Python'ın
/// ``agent.run.accepted`` olayını AYRI anlamlarda tutar: ilki backend'in sorumluluğu
/// aldığı an (bu kaydın oluşumu), ikincisi Python'ın işi kalıcı olarak kabul etmesidir
/// (B5 projection'ı olay olaylarından günceller; bu enum B5'te genişletilir).
/// </summary>
public enum AgentRunStatus
{
    /// <summary>Backend işi kabul etti; komut outbox kaydıyla aynı transaction'da yazıldı.</summary>
    Accepted = 0
}
