using BlogApp.Server.Domain.Enums;
using BlogApp.Server.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;

namespace BlogApp.Server.Infrastructure.Services;

public class IdempotencyCleanupService : BackgroundService
{
    private static readonly TimeSpan CleanupInterval = TimeSpan.FromHours(6);
    private static readonly TimeSpan RetentionPeriod = TimeSpan.FromDays(30);
    private readonly IServiceScopeFactory _scopeFactory;
    private readonly ILogger<IdempotencyCleanupService> _logger;

    public IdempotencyCleanupService(
        IServiceScopeFactory scopeFactory,
        ILogger<IdempotencyCleanupService> logger)
    {
        _scopeFactory = scopeFactory;
        _logger = logger;
    }

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        _logger.LogInformation(
            "IdempotencyCleanupService started. Cleanup interval: {Interval}, retention: {Retention}",
            CleanupInterval,
            RetentionPeriod);

        await Task.Delay(TimeSpan.FromMinutes(1), stoppingToken);

        while (!stoppingToken.IsCancellationRequested)
        {
            try
            {
                await CleanupAsync(stoppingToken);
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Error occurred during idempotency cleanup");
            }

            await Task.Delay(CleanupInterval, stoppingToken);
        }
    }

    private async Task CleanupAsync(CancellationToken cancellationToken)
    {
        using var scope = _scopeFactory.CreateScope();
        var context = scope.ServiceProvider.GetRequiredService<AppDbContext>();
        var cutoff = DateTime.UtcNow.Subtract(RetentionPeriod);

        var deletedIdempotencyRecords = await context.IdempotencyRecords
            .IgnoreQueryFilters()
            .Where(r => !r.IsDeleted)
            .Where(r => r.Status != IdempotencyRecordStatus.Processing)
            .Where(r => r.CompletedAt != null && r.CompletedAt < cutoff)
            .ExecuteDeleteAsync(cancellationToken);

        var deletedConsumerInboxMessages = await context.ConsumerInboxMessages
            .IgnoreQueryFilters()
            .Where(r => !r.IsDeleted)
            .Where(r => r.Status != ConsumerInboxStatus.Processing)
            .Where(r => r.ProcessedAt != null && r.ProcessedAt < cutoff)
            .ExecuteDeleteAsync(cancellationToken);

        if (deletedIdempotencyRecords > 0 || deletedConsumerInboxMessages > 0)
        {
            _logger.LogInformation(
                "Cleaned up {IdempotencyCount} idempotency records and {ConsumerInboxCount} consumer inbox rows older than {Cutoff}",
                deletedIdempotencyRecords,
                deletedConsumerInboxMessages,
                cutoff);
        }
        else
        {
            _logger.LogDebug("No idempotency records eligible for cleanup");
        }
    }
}
