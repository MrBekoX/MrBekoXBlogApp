using BlogApp.BuildingBlocks.Messaging;
using BlogApp.Core.Application.Common.Messaging;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.DependencyInjection.Extensions;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;

namespace BlogApp.Infrastructure.Messaging;

/// <summary>
/// B5 projection hat kayıtları (plan B5 backend listesi). ÖN KOŞUL:
/// <see cref="RabbitMqMessagingDependencyInjection.AddRabbitMqAgentMessaging"/> (B2)
/// kayıtlı olmalıdır — consumer, connection manager + RabbitMqSettings'i DI'dan alır.
/// B6/B10 tarafından Program.cs'te çağrılır:
///   builder.Services.AddRabbitMqAgentMessaging(configuration);
///   builder.Services.AddAgentEventProjection(configuration);
/// UI bildirimi: <see cref="IAgentRunNotifier"/> için TryAdd ile no-op kaydedilir;
/// Presentation (Program.cs) SignalR implementasyonunu SONRA kaydederse son kayıt
/// çözümlenir (hub kaydı yoksa API no-op ile sorunsuz çalışır).
/// K3: kuyruğun kendisi declarer (AgentTopologyInitializer) tarafından bildirilir;
/// consumer pasif tüketir.
/// </summary>
public static class AgentEventProjectionDependencyInjection
{
    public static IServiceCollection AddAgentEventProjection(
        this IServiceCollection services, IConfiguration configuration)
    {
        services.TryAddSingleton<IAgentRunNotifier, NoOpAgentRunNotifier>();

        services.TryAddSingleton<AgentContractValidator>(new AgentContractValidator());
        services.AddScoped<AgentRunEventProjectionHandler>();
        services.AddSingleton<AgentEventProjectionConsumer>();
        services.AddSingleton<IAgentBrokerConsumer>(sp => sp.GetRequiredService<AgentEventProjectionConsumer>());
        services.AddHostedService<AgentEventProjectionService>();

        return services;
    }
}

/// <summary>Bildirim hattı takılı değilken projection'ın çalışmasını sağlayan no-op.</summary>
public sealed class NoOpAgentRunNotifier(ILogger<NoOpAgentRunNotifier> logger) : IAgentRunNotifier
{
    public Task NotifyAsync(AgentRunNotification notification, CancellationToken cancellationToken = default)
    {
        logger.LogDebug(
            "[AgentEvents] notifier takılı değil; bildirim yoksayıldı: run {RunId} type {Type}",
            notification.RunId, notification.MessageType);
        return Task.CompletedTask;
    }
}

/// <summary>Consumer ömrünü uygulama ömrüne bağlar; broker kapalıysa döngü çökmez.</summary>
public sealed class AgentEventProjectionService(
    AgentEventProjectionConsumer consumer,
    ILogger<AgentEventProjectionService> logger) : BackgroundService
{
    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        while (!stoppingToken.IsCancellationRequested)
        {
            try
            {
                await consumer.StartAsync(stoppingToken);
                logger.LogInformation("[AgentEvents] olay projection consumer başladı");
                break;
            }
            catch (Exception exception) when (exception is not OperationCanceledException)
            {
                // Broker kapalı: aplikasyon ayağa kalkmaya devam etsin; tekrar dener.
                logger.LogWarning("[AgentEvents] consumer başlatılamadı, tekrar denenecek: {Message}", exception.Message);
                await Task.Delay(TimeSpan.FromSeconds(5), stoppingToken);
            }
        }

        try
        {
            await Task.Delay(Timeout.Infinite, stoppingToken);
        }
        catch (OperationCanceledException)
        {
            // kapanış
        }

        await consumer.StopAsync(CancellationToken.None);
    }
}
