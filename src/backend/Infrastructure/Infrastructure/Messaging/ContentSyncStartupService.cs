using BlogApp.Core.Application.Common.AuthorProfile;
using BlogApp.Core.Application.Common.Options;
using BlogApp.Core.Application.Features.AgentFeature.Services;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Storage;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;
using Npgsql;

namespace BlogApp.Infrastructure.Messaging;

/// <summary>
/// Commits the initial content snapshot before HTTP startup. Only the database
/// outbox is required here; publication and embedding are separate worker paths.
/// </summary>
public sealed class ContentSyncStartupService(
    IServiceScopeFactory scopeFactory,
    IOptions<AgentContentSyncSettings> options,
    ILogger<ContentSyncStartupService> logger) : IHostedService
{
    public async Task StartAsync(CancellationToken cancellationToken)
    {
        var settings = options.Value;
        if (!settings.Enabled)
        {
            logger.LogInformation("Agent startup content sync is disabled.");
            return;
        }

        for (var attempt = 1; ; attempt++)
        {
            cancellationToken.ThrowIfCancellationRequested();
            try
            {
                await using var scope = scopeFactory.CreateAsyncScope();
                var profile = scope.ServiceProvider.GetRequiredService<IAuthorProfileSource>().GetCurrent();
                if (!profile.IsAvailable)
                {
                    throw new InvalidOperationException(
                        "Agent startup requires a valid public approved canonical author profile.");
                }

                var sync = scope.ServiceProvider.GetRequiredService<ContentSnapshotSyncService>();
                var summary = await sync.RunSyncAsync(cancellationToken);
                logger.LogInformation(
                    "Agent startup snapshot committed: {SyncId}, {ItemCount} articles, {TotalBatches} batches.",
                    summary.SyncId, summary.ItemCount, summary.TotalBatches);
                return;
            }
            catch (Exception exception) when (
                attempt < settings.StartupMaxAttempts && IsTransientDatabaseFailure(exception))
            {
                logger.LogWarning(exception,
                    "Agent startup content sync failed transiently (attempt {Attempt}/{MaxAttempts}); retrying with a fresh scope.",
                    attempt, settings.StartupMaxAttempts);
                await Task.Delay(TimeSpan.FromSeconds(settings.StartupRetryDelaySeconds), cancellationToken);
            }
            catch (Exception exception)
            {
                logger.LogCritical(exception, "Agent startup content sync failed; HTTP startup is refused.");
                throw;
            }
        }
    }

    private static bool IsTransientDatabaseFailure(Exception exception) => exception switch
    {
        NpgsqlException { IsTransient: true } => true,
        TimeoutException => true,
        DbUpdateException { InnerException: { } inner } => IsTransientDatabaseFailure(inner),
        RetryLimitExceededException { InnerException: { } inner } => IsTransientDatabaseFailure(inner),
        _ => false,
    };

    public Task StopAsync(CancellationToken cancellationToken) => Task.CompletedTask;
}
