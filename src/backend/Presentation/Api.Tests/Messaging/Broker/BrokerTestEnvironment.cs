using BlogApp.BuildingBlocks.Messaging;
using RabbitMQ.Client;

namespace BlogApp.Presentation.Api.Tests.Messaging.Broker;

/// <summary>
/// B2 broker test ortamı: docker compose rabbitmq (RabbitMQ 4.2) üzerinde vhost
/// ``blogapp_dev`` ve servis kullanıcıları Python tarafının conftest'i ile aynı
/// provizyonu kullanır. Değerler env ile override edilebilir.
/// </summary>
internal static class BrokerTestEnvironment
{
    internal static string Host => Environment.GetEnvironmentVariable("RABBITMQ_HOST") ?? "127.0.0.1";

    internal static int Port => int.TryParse(Environment.GetEnvironmentVariable("RABBITMQ_PORT"), out var port) ? port : 5672;

    internal static Uri ManagementBaseAddress => new(
        new Uri(Environment.GetEnvironmentVariable("RABBITMQ_MGMT_URL") ?? "http://127.0.0.1:15672/api")
            .GetLeftPart(UriPartial.Authority) + "/");

    internal static string VirtualHost => Environment.GetEnvironmentVariable("RABBITMQ_VHOST") ?? "blogapp_dev";

    internal static (string User, string Password) BackendUser =>
        (Environment.GetEnvironmentVariable("RABBITMQ_BACKEND_USER") ?? "backend_svc",
         Environment.GetEnvironmentVariable("RABBITMQ_BACKEND_PASSWORD") ?? "backend_svc_dev");

    internal static (string User, string Password) AdminUser =>
        (Environment.GetEnvironmentVariable("RABBITMQ_ADMIN_USER") ?? "blogapp",
         Environment.GetEnvironmentVariable("RABBITMQ_ADMIN_PASSWORD") ?? "blogapp_dev");

    internal static string RabbitMqContainer =>
        Environment.GetEnvironmentVariable("RABBITMQ_DOCKER_CONTAINER") ?? "blogapp-rabbitmq";

    internal static RabbitMqSettings BackendSettings() => new()
    {
        Host = Host,
        Port = Port,
        UserName = BackendUser.User,
        Password = BackendUser.Password,
        VirtualHost = VirtualHost,
        ClientProvidedName = "backend-net-tests",
        RequestedHeartbeatSeconds = 30,
        NetworkRecoveryIntervalSeconds = 2,
        // Declarer: ayrı operasyonel kimlik (RabbitMQ 4.2 DLX declare kuralı gereği
        // events exchange'ine write'ı olan kimlik; uygulama yayını için KULLANILMAZ).
        DeclarerUserName = AdminUser.User,
        DeclarerPassword = AdminUser.Password,
    };

    internal static RabbitMqSettings AdminSettings(string clientName = "backend-net-tests-admin") => new()
    {
        Host = Host,
        Port = Port,
        UserName = AdminUser.User,
        Password = AdminUser.Password,
        VirtualHost = VirtualHost,
        ClientProvidedName = clientName,
        NetworkRecoveryIntervalSeconds = 2,
    };

    internal static ConnectionFactory FactoryFor(RabbitMqSettings settings) => new()
    {
        Endpoint = new AmqpTcpEndpoint(settings.Host, settings.Port),
        UserName = settings.UserName,
        Password = settings.Password,
        VirtualHost = settings.VirtualHost,
        ClientProvidedName = settings.ClientProvidedName,
        AutomaticRecoveryEnabled = settings.NetworkRecoveryIntervalSeconds > 0,
        TopologyRecoveryEnabled = true,
        NetworkRecoveryInterval = TimeSpan.FromSeconds(Math.Max(settings.NetworkRecoveryIntervalSeconds, 1)),
    };

    /// <summary>Broker'a yönetim amaçlı kısa ömürlü bağlantı açar (doğrulama okumaları için).</summary>
    internal static async Task<IConnection> OpenAdminConnectionAsync(
        CancellationToken cancellationToken = default,
        string clientName = "backend-net-tests-admin")
    {
        var connection = await FactoryFor(AdminSettings(clientName)).CreateConnectionAsync(cancellationToken);
        return connection;
    }
}
