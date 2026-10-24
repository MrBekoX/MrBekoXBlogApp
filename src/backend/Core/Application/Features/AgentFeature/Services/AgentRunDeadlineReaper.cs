using BlogApp.Core.Application.Common.Interfaces.Data;
using BlogApp.Core.Domain.Entities;
using BlogApp.Core.Domain.Enums;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging;

namespace BlogApp.Core.Application.Features.AgentFeature.Services;

/// <summary>
/// Backend tarafı deadline reaper (B7; plan satır 434: "backend ve agent
/// tarafında süresi geçen işleri kapatan reaper"). Broker TTL ile düşen bir
/// mesajın işi belirsiz bırakmaması için backend, kabul edilmiş ama deadline'ı
/// geçmiş AgentRun kayıtlarını kapatır:
///
/// - Status Accepted (çözümlenmemiş) + DeadlineAt geçmiş → Status=Failed;
///   TerminalAt ve ResultJson reaper damgasıyla yazılır. Aktif-iş kotaları
///   (sahip başı + sistem düzeyi) böylece tıkanmış işlerle dolmaz.
/// - Agent tarafı daha sonra gerçek terminal olayı getirirse B5 projection
///   kuralı uygular: daha YÜKSEK sequence'li terminal olay terminal durumun
///   üzerine yazılabilir (iki terminal çelişirse yüksek sequence kazanır);
///   reaper'ın erken kapatması doğru sonucu ENGELLEMEZ.
/// - Cancel intent'i açık işlere dokunma tercihi YOKTUR: iptal istenmiş olsa
///   bile deadline geçtiyse run kapatılır; agent tarafındaki cancel akışı
///   terminali cancelled olarak üretirse projection günceller.
///
/// Infrastructure hosts this service periodically. The final UPDATE rechecks status
/// and deadline, so a terminal projection committed after candidate selection wins.
/// </summary>
public sealed class AgentRunDeadlineReaper(
    IApplicationDbContext dbContext,
    ILogger<AgentRunDeadlineReaper> logger)
{
    /// <summary>Süresi geçmiş çözümlenmemiş run'ları kapatır; kapatılan run sayısını döndürür.</summary>
    public async Task<int> ReapExpiredAsync(CancellationToken cancellationToken = default)
    {
        var now = DateTime.UtcNow;
        var expired = await dbContext.AgentRuns
            .AsNoTracking()
            .TagWith("agent-deadline-candidates")
            .Where(r => r.Status == AgentRunStatus.Accepted && r.DeadlineAt < now)
            .OrderBy(r => r.DeadlineAt)
            .Take(ReaperBatchLimit)
            .Select(r => r.Id)
            .ToListAsync(cancellationToken);
        if (expired.Count == 0)
        {
            return 0;
        }

        var closed = await dbContext.AgentRuns
            .Where(r => expired.Contains(r.Id)
                        && r.Status == AgentRunStatus.Accepted && r.DeadlineAt < now)
            .ExecuteUpdateAsync(update => update
                .SetProperty(r => r.Status, AgentRunStatus.Failed)
                .SetProperty(r => r.TerminalAt, now)
                .SetProperty(r => r.ResultJson, AgentDeadlineResultJson), cancellationToken);
        logger.LogWarning(
            "[AgentReaper] {Count} süresi geçmiş agent işi kapatıldı (örnek run {SampleRunId})",
            closed, expired[0]);
        return closed;
    }

    /// <summary>Tek çevrimde kapatılacak en fazla run sayısı (uzun kilitleri önler).</summary>
    public const int ReaperBatchLimit = 100;

    /// <summary>Reaper ile kapatılan run'ların sonuç damgası (terminal olay gelirse projection günceller).</summary>
    public const string AgentDeadlineResultJson = """{"terminal":"deadline_exceeded","closed_by":"backend-reaper"}""";
}
