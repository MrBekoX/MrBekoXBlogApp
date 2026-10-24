using BlogApp.BuildingBlocks.Messaging;
using Microsoft.Extensions.Diagnostics.HealthChecks;
using Microsoft.Extensions.Options;

namespace BlogApp.Presentation.Api.Health;

/// <summary>
/// Broker bağlantı readiness kontrolü (plan satır 561: liveness'tan AYRI).
///
/// Kasıtlı tasarım: bu kontrol "broker'a şimdi bağlanabiliyor musun" sorusunu
/// yanıtlar ve yalnız /health/agent (tag "agent") altında raporlanır. Ana
/// /health/ready'e bağlanmamasının nedeni K3 kuralıdır — broker kapalıyken
/// uygulama ayakta kalmalı, kabulü DB outbox'ına yazmaya devam etmeli
/// (OutboxRelayService kendi döngüsünde tekrar bağlanır; [RMQ-DOTNET#C1]
/// uzun ömürlü bağlantı + otomatik recovery bu kontrolün yalnız gözlemci
/// olmasını sağlar: kontrol kendi bağlantısı açmaz, yöneticinin paylaşılán
/// bağlantısını kullanır).
/// </summary>
public sealed class AgentBrokerHealthCheck(
    IRabbitMqConnectionManager connectionManager,
    IOptions<AgentHealthOptions> options) : IHealthCheck
{
    public async Task<HealthCheckResult> CheckHealthAsync(
        HealthCheckContext context, CancellationToken cancellationToken = default)
    {
        var settings = options.Value;
        try
        {
            using var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
            timeout.CancelAfter(TimeSpan.FromSeconds(Math.Max(settings.BrokerConnectTimeoutSeconds, 1)));

            var connection = await connectionManager.GetConnectionAsync(timeout.Token);
            if (connection.IsOpen)
            {
                return HealthCheckResult.Healthy(
                    "broker bağlantısı açık",
                    data: new Dictionary<string, object>
                    {
                        ["endpoint"] = FormattableString.Invariant(
                            $"{connection.Endpoint.HostName ?? "?"}:{connection.Endpoint.Port}"),
                        ["client_name"] = connection.ClientProvidedName ?? "unknown",
                    });
            }

            // Bağlantı nesnesi var ama kapalı: GetConnectionAsync recovery'de yeniden açar;
            // kontrol Degraded döner (kabul yolu çalışır, yayın gecikir).
            return HealthCheckResult.Degraded("broker bağlantısı kapalı (otomatik recovery sürüyor)");
        }
        catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested)
        {
            return new HealthCheckResult(
                context.Registration.FailureStatus,
                $"broker bağlantısı {settings.BrokerConnectTimeoutSeconds}s içinde kurulamadı");
        }
        catch (Exception exception)
        {
            return new HealthCheckResult(
                context.Registration.FailureStatus,
                "broker bağlantısı kurulamadı (kabul yolu DB outbox'ıyla çalışmaya devam eder)",
                exception);
        }
    }
}
