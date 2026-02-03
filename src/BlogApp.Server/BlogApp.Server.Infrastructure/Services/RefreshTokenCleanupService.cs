using BlogApp.Server.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;

namespace BlogApp.Server.Infrastructure.Services;

/// <summary>
/// Background service that periodically cleans up expired refresh tokens.
/// Prevents database bloat from accumulated expired tokens.
/// </summary>
public class RefreshTokenCleanupService : BackgroundService
{
    private readonly IServiceScopeFactory _scopeFactory;
    private readonly ILogger<RefreshTokenCleanupService> _logger;
    
    // Run cleanup every 6 hours
    private static readonly TimeSpan CleanupInterval = TimeSpan.FromHours(6);
    
    // Delete tokens that expired more than 7 days ago (keep recent ones for audit trail)
    private static readonly TimeSpan TokenRetentionPeriod = TimeSpan.FromDays(7);

    public RefreshTokenCleanupService(
        IServiceScopeFactory scopeFactory,
        ILogger<RefreshTokenCleanupService> logger)
    {
        _scopeFactory = scopeFactory;
        _logger = logger;
    }

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        _logger.LogInformation("RefreshTokenCleanupService started. Cleanup interval: {Interval}", CleanupInterval);

        // Initial delay to let the application start up
        await Task.Delay(TimeSpan.FromMinutes(1), stoppingToken);

        while (!stoppingToken.IsCancellationRequested)
        {
            try
            {
                await CleanupExpiredTokensAsync(stoppingToken);
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Error occurred during refresh token cleanup");
            }

            await Task.Delay(CleanupInterval, stoppingToken);
        }

        _logger.LogInformation("RefreshTokenCleanupService stopped.");
    }

    private async Task CleanupExpiredTokensAsync(CancellationToken cancellationToken)
    {
        using var scope = _scopeFactory.CreateScope();
        var context = scope.ServiceProvider.GetRequiredService<AppDbContext>();

        var cutoffDate = DateTime.UtcNow.Subtract(TokenRetentionPeriod);

        try
        {
            // Delete expired tokens that are older than retention period
            var deletedCount = await context.RefreshTokens
                .Where(t => t.ExpiresAt < cutoffDate)
                .ExecuteDeleteAsync(cancellationToken);

            if (deletedCount > 0)
            {
                _logger.LogInformation(
                    "Cleaned up {Count} expired refresh tokens older than {CutoffDate}",
                    deletedCount,
                    cutoffDate);
            }
            else
            {
                _logger.LogDebug("No expired refresh tokens to clean up");
            }

            // Also clean up revoked tokens that are older than retention period
            var revokedDeletedCount = await context.RefreshTokens
                .Where(t => t.RevokedAt != null && t.RevokedAt < cutoffDate)
                .ExecuteDeleteAsync(cancellationToken);

            if (revokedDeletedCount > 0)
            {
                _logger.LogInformation(
                    "Cleaned up {Count} revoked refresh tokens older than {CutoffDate}",
                    revokedDeletedCount,
                    cutoffDate);
            }
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Failed to cleanup expired refresh tokens");
            throw;
        }
    }
}
