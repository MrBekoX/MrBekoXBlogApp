using BlogApp.Core.Domain.Enums;
using BlogApp.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Diagnostics.HealthChecks;
using Microsoft.Extensions.Options;

namespace BlogApp.Presentation.Api.Health;

/// <summary>
/// Outbox backlog kontrolü (plan satır 561-562): "Broker kapalıyken kabul edilen
/// işin beklediğini doğru göster; backlog kapasitesine göre kabulü sınırlayabil."
///
/// İki ayrı sinyal taşır:
/// - Çözümlenmemiş outbox kaydı SAYISI (Pending + bayat Claimed): relay'in
///   zorlandığı birikim; kabul kapısı B7 MaxActiveRunsTotal ile zaten sınırlıdır,
///   bu kontrol o sınıra yakınsamayı operatöre GÖSTERİR.
/// - En eski çözümlenmemiş kaydın YAŞI: "kabul edilen iş bekliyor" durumunun
///   süre karşılığı (broker kesintisinde kabul edilen iş kaybolmaz, bekler —
///   B3 kabul ölçütü; bu kontrol o bekleme penceresini gözlemlenbilir kılar).
///
/// Kabul davranışını DEĞİŞTİRMEZ: yalnız /health/agent altında raporlanır.
/// AppDbContext scoped kayıtlı olduğundan kapsam fabrikası üzerinden çözülür
/// (OutboxRelayService deseni; singleton health check'te captive dependency yok).
/// Yayınlanmış kayıtlar (Published) backlog sayılmaz; saklama/silme politikası
/// operations rehberindeki saklama-ve-replay penceresi kararındadır.
/// </summary>
public sealed class AgentOutboxBacklogHealthCheck(
    IServiceScopeFactory scopeFactory,
    IOptions<AgentHealthOptions> options) : IHealthCheck
{
    public async Task<HealthCheckResult> CheckHealthAsync(
        HealthCheckContext context, CancellationToken cancellationToken = default)
    {
        var settings = options.Value;

        int pendingCount;
        DateTime oldestCreatedAt;
        try
        {
            await using var scope = scopeFactory.CreateAsyncScope();
            var dbContext = scope.ServiceProvider.GetRequiredService<AppDbContext>();
            var cutoff = DateTime.UtcNow.AddMinutes(-Math.Max(settings.OutboxGraceMinutes, 0));

            var rows = await dbContext.OutboxMessages
                .AsNoTracking()
                .Where(m => m.Status == AgentOutboxStatus.Pending
                            || (m.Status == AgentOutboxStatus.Claimed
                                && m.ClaimLeaseUntil != null
                                && m.ClaimLeaseUntil < DateTime.UtcNow)) // bayat claim = kayıp confirm/çökmüş publisher
                .Where(m => m.CreatedAt <= cutoff) // grace: relay'in normal penceresi alarm üretmesin
                .Select(m => new { m.CreatedAt })
                .ToListAsync(cancellationToken);

            pendingCount = rows.Count;
            oldestCreatedAt = rows.Count > 0 ? rows.Min(r => r.CreatedAt) : DateTime.UtcNow;
        }
        catch (Exception exception)
        {
            return new HealthCheckResult(
                context.Registration.FailureStatus,
                "outbox backlog sorgusu başarısız (veritabanı erişilemiyor olabilir)",
                exception);
        }

        var oldestAgeMinutes = Math.Max((DateTime.UtcNow - oldestCreatedAt).TotalMinutes, 0);
        var data = new Dictionary<string, object>
        {
            ["pending_count"] = pendingCount,
            ["oldest_pending_age_minutes"] = Math.Round(oldestAgeMinutes, 1),
            ["warn_count"] = settings.OutboxWarnPendingCount,
            ["unhealthy_count"] = settings.OutboxUnhealthyPendingCount,
            ["warn_age_minutes"] = settings.OutboxWarnOldestMinutes,
            ["unhealthy_age_minutes"] = settings.OutboxUnhealthyOldestMinutes,
        };

        if (pendingCount >= settings.OutboxUnhealthyPendingCount
            || oldestAgeMinutes >= settings.OutboxUnhealthyOldestMinutes)
        {
            return new HealthCheckResult(
                context.Registration.FailureStatus,
                $"outbox backlog eşiği aşıldı: {pendingCount} kayıt, en eski {Math.Round(oldestAgeMinutes, 1)} dk "
                + "(broker/topoloji sorununda operations/dlq-inceleme-ve-replay.md adımları izlenir)",
                data: data);
        }

        if (pendingCount >= settings.OutboxWarnPendingCount
            || oldestAgeMinutes >= settings.OutboxWarnOldestMinutes)
        {
            return HealthCheckResult.Degraded(
                $"outbox birikiyor: {pendingCount} kayıt, en eski {Math.Round(oldestAgeMinutes, 1)} dk "
                + "(broker kapalıysa kabul edilen iş BEKLEMEDE — kayıp yok)",
                data: data);
        }

        return HealthCheckResult.Healthy("outbox backlog sınır içinde", data: data);
    }
}
