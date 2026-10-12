namespace BlogApp.Core.Domain.Enums;

/// <summary>
/// Backend'in AgentRun kaydının durumu. B3'te tek değer vardı: kabul.
/// Plan (02-rabbitmq-haberlesme-plani.md satır 305) kabul durumu ile Python'ın
/// ``agent.run.accepted`` olayını AYRI anlamlarda tutar: ilki backend'in sorumluluğu
/// aldığı an (bu kaydın oluşumu), ikincisi Python'ın işi kalıcı olarak kabul etmesidir.
/// B5 projection'ı olaylarıyla günceller: yalnız TERMINAL olaylar durumu Accepted'dan
/// çıkarır (non-terminal progress/mode_selected/needs_input durum değiştirmez; böylece
/// B3 kabul akışındaki "çözümlenmemiş iş" sayımı Accepted koşuluyla doğru kalır).
/// Değerler ADDITIVE'dir; mevcut Accepted=0 değişmez.
/// </summary>
public enum AgentRunStatus
{
    /// <summary>Backend işi kabul etti; komut outbox kaydıyla aynı transaction'da yazıldı.</summary>
    Accepted = 0,

    /// <summary>Terminal başarı: agent.run.completed snapshot'ı uygulandı (B5 projection).</summary>
    Completed = 1,

    /// <summary>Terminal kısmi başarı: agent.run.partially_completed snapshot'ı uygulandı.</summary>
    PartiallyCompleted = 2,

    /// <summary>Terminal başarısızlık: agent.run.failed uygulandı.</summary>
    Failed = 3,

    /// <summary>Terminal iptal: agent.run.cancelled uygulandı.</summary>
    Cancelled = 4
}

/// <summary>Projection'ın terminal-öncelik kuralının paylaşılan tanımı (B5).</summary>
public static class AgentRunStatusRules
{
    /// <summary>Terminal durumlar: bir kez yazıldıktan sonra eski olay geriye götüremez.</summary>
    public static readonly IReadOnlyCollection<AgentRunStatus> TerminalStatuses =
    [
        AgentRunStatus.Completed,
        AgentRunStatus.PartiallyCompleted,
        AgentRunStatus.Failed,
        AgentRunStatus.Cancelled
    ];

    public static bool IsTerminal(this AgentRunStatus status) => TerminalStatuses.Contains(status);
}
