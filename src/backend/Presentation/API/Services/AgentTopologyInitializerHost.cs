using BlogApp.BuildingBlocks.Messaging;
using Microsoft.Extensions.Options;

namespace BlogApp.Presentation.Api.Services;

/// <summary>
/// K3 kablolaması (B10 Program.cs): topoloji declarer'ı uygulama başlangıcında
/// InitializeAsync ile çağırır. Broker kapalıysa uygulama AYAĞA KALKMAYA DEVAM
/// eder (fail-fast OLMAYAN kabul yolu): log + sınırlı geri çekilmeli tekrar;
/// consumer/relay kayıtları kendi döngülerinde pasif declare tekrarıyla toparlanır.
/// </summary>
public sealed class AgentTopologyInitializerHost(
    AgentTopologyInitializer initializer,
    IOptions<RabbitMqSettings> settings,
    ILogger<AgentTopologyInitializerHost> logger) : BackgroundService
{
    private const int MaxAttempts = 10;

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        for (var attempt = 1; attempt <= MaxAttempts && !stoppingToken.IsCancellationRequested; attempt++)
        {
            try
            {
                await initializer.InitializeAsync(stoppingToken);
                logger.LogInformation(
                    "[AgentTopology] topoloji hazır (vhost {VHost}, deneme {Attempt})",
                    settings.Value.VirtualHost, attempt);
                return;
            }
            catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested)
            {
                return;
            }
            catch (Exception exception)
            {
                logger.LogWarning(
                    "[AgentTopology] topoloji bildirimi başarısız (deneme {Attempt}/{Max}): {Message}",
                    attempt, MaxAttempts, exception.Message);
                try
                {
                    await Task.Delay(TimeSpan.FromSeconds(5 * attempt), stoppingToken);
                }
                catch (OperationCanceledException)
                {
                    return;
                }
            }
        }

        // Üst sınıra ulaşıldı: uygulama çalışmaya devam eder; relay/consumer
        // kendi bağlantı döngülerinde topoloji tekrarını dener.
        logger.LogWarning(
            "[AgentTopology] topoloji bildirimi {Max} denemede tamamlanamadı; arka plan bileşenleri kendi döngülerinde tekrar deneyecek",
            MaxAttempts);
    }
}
