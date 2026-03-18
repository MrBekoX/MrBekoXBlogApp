using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.DependencyInjection;
using BlogApp.Server.Application.Common.Interfaces.Services;

namespace BlogApp.Server.Infrastructure.Services;

public class OutboxPublisherHostedService(
    IServiceScopeFactory scopeFactory,
    ILogger<OutboxPublisherHostedService> logger) : BackgroundService
{
    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        using var timer = new PeriodicTimer(TimeSpan.FromSeconds(1));

        while (!stoppingToken.IsCancellationRequested)
        {
            try
            {
                await using var scope = scopeFactory.CreateAsyncScope();
                var outboxService = scope.ServiceProvider.GetRequiredService<IOutboxService>();
                var published = await outboxService.PublishPendingAsync(batchSize: 20, stoppingToken);

                if (published > 0)
                {
                    logger.LogInformation("Published {Count} pending outbox message(s)", published);
                }
            }
            catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested)
            {
                break;
            }
            catch (Exception ex)
            {
                logger.LogError(ex, "Outbox publisher loop failed");
            }

            await timer.WaitForNextTickAsync(stoppingToken);
        }
    }
}

