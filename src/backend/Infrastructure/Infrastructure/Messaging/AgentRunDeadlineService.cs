using BlogApp.Core.Application.Common.Options;
using BlogApp.Core.Application.Features.AgentFeature.Services;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;

namespace BlogApp.Infrastructure.Messaging;

/// <summary>Recover expired API runs even when no worker terminal event arrives.</summary>
public sealed class AgentRunDeadlineService(
    IServiceScopeFactory scopeFactory,
    IOptions<AgentAcceptanceSettings> options,
    ILogger<AgentRunDeadlineService> logger) : BackgroundService
{
    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        using var timer = new PeriodicTimer(TimeSpan.FromSeconds(options.Value.DeadlineReaperIntervalSeconds));
        try
        {
            do
            {
                try
                {
                    await using var scope = scopeFactory.CreateAsyncScope();
                    var reaper = scope.ServiceProvider.GetRequiredService<AgentRunDeadlineReaper>();
                    await reaper.ReapExpiredAsync(stoppingToken);
                }
                catch (Exception exception) when (exception is not OperationCanceledException)
                {
                    logger.LogError(exception, "Backend agent deadline recovery failed; the next interval will retry.");
                }
            } while (await timer.WaitForNextTickAsync(stoppingToken));
        }
        catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested)
        {
            // Normal host shutdown; no in-flight database work is left detached.
        }
    }
}
