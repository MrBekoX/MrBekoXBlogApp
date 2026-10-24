namespace BlogApp.Core.Application.Common.Options;

/// <summary>
/// Agent iş kabul politikası — appsettings "AgentAcceptance" section (B3).
/// Kota oranları ürün kararıdır (K5); varsayılanlar muhafazakâr seçildi ve
/// üretimde yapılandırma ile değiştirilir.
/// </summary>
public sealed class AgentAcceptanceSettings
{
    public const string SectionName = "AgentAcceptance";

    /// <summary>Misafir oturumların agent işi kabul edip edemeyeceği (K5: ürün kararı).</summary>
    public bool AllowGuestRuns { get; set; } = true;

    /// <summary>Sahip başına eşzamanlı (çözümlenmemiş) iş üst sınırı; limit kontrolü kabulde uygulanır.</summary>
    public int MaxActiveRunsPerOwner { get; set; } = 3;

    /// <summary>Sistem düzeyi eşzamanlı (çözümlenmemiş) iş üst sınırı (B7 backpressure):
    /// tek kullanıcının kotası boş olsa bile toplam kapasite aşıldığında yeni iş
    /// kabul edilmez; kuyruk derinliğine ek olarak kabul edilmiş iş backlog'una
    /// kapı düzeyinde sınır koyar (plan satır 422-423).</summary>
    public int MaxActiveRunsTotal { get; set; } = 100;

    /// <summary>Mod bazlı iş bitiş zamanı (dakika); K6: deadline sahibi backend'dir.</summary>
    public int FastDeadlineMinutes { get; set; } = 2;

    public int AnalysisDeadlineMinutes { get; set; } = 5;

    public int DeepResearchDeadlineMinutes { get; set; } = 15;

    /// <summary>mode_preference=auto için varsayılan bitiş zamanı (dakika); mod seçimi Python'dadır.</summary>
    public int AutoDeadlineMinutes { get; set; } = 5;

    /// <summary>Interval for backend recovery of expired accepted runs.</summary>
    public int DeadlineReaperIntervalSeconds { get; set; } = 15;
}
