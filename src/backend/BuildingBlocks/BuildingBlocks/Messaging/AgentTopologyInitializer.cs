using RabbitMQ.Client;

namespace BlogApp.BuildingBlocks.Messaging;

/// <summary>
/// Plan topolojisinin idempotent declarer'ı (K3: tek declarer backend dağıtımı).
/// Aynı ad + aynı argümanla tekrarlı kurulum topolojiyi bozmaz; farklı argümanla
/// declare PRECONDITION_FAILED üretir ve topoloji korunur.
///
/// Declarer, ayarlarda tanımlı ayrı operasyonel kimliği kullanır
/// (<see cref="RabbitMqSettings.DeclarerUserName"/>): RabbitMQ 4.2'de DLX'li kuyruk
/// yaratımı declarer'dan o kuyruğa read + DLX exchange'ine write ister; uygulama servis
/// kullanıcısının yetkileri ise yalnız kendi yayın/tüketim kapsamıyla sınırlıdır.
/// Declarer kimliği uygulama mesajı yayınlamak için kullanılmaz.
/// </summary>
public sealed class AgentTopologyInitializer : IAsyncDisposable
{
    private readonly RabbitMqSettings _settings;
    private readonly RabbitMqConnectionManager _declarerConnections;

    public AgentTopologyInitializer(RabbitMqSettings settings)
    {
        _settings = settings;
        _declarerConnections = new RabbitMqConnectionManager(DeclarerSettings());
    }

    private RabbitMqSettings DeclarerSettings() => new()
    {
        Host = _settings.Host,
        Port = _settings.Port,
        VirtualHost = _settings.VirtualHost,
        ClientProvidedName = _settings.ClientProvidedName + "-declarer",
        RequestedHeartbeatSeconds = _settings.RequestedHeartbeatSeconds,
        NetworkRecoveryIntervalSeconds = _settings.NetworkRecoveryIntervalSeconds,
        UserName = string.IsNullOrEmpty(_settings.DeclarerUserName)
            ? _settings.UserName
            : _settings.DeclarerUserName,
        Password = string.IsNullOrEmpty(_settings.DeclarerPassword)
            ? _settings.Password
            : _settings.DeclarerPassword,
        MaxPublishBytes = _settings.MaxPublishBytes,
        RetryTierSeconds = _settings.RetryTierSeconds,
    };

    public async Task InitializeAsync(CancellationToken cancellationToken = default)
    {
        var connection = await _declarerConnections.GetConnectionAsync(cancellationToken);
        await using var channel = await connection.CreateChannelAsync(cancellationToken: cancellationToken);

        foreach (var exchange in AgentMessagingTopology.Exchanges(_settings.RetryTierSeconds))
        {
            await channel.ExchangeDeclareAsync(
                exchange,
                ExchangeType.Topic,
                durable: true,
                autoDelete: false,
                arguments: null,
                cancellationToken: cancellationToken);
        }

        foreach (var queue in AgentMessagingTopology.Queues(_settings.RetryTierSeconds))
        {
            await channel.QueueDeclareAsync(
                queue.Name,
                durable: queue.Durable,
                exclusive: false,
                autoDelete: false,
                arguments: queue.Arguments,
                cancellationToken: cancellationToken);
        }

        foreach (var binding in AgentMessagingTopology.Bindings(_settings.RetryTierSeconds))
        {
            await channel.QueueBindAsync(
                binding.Queue,
                binding.Exchange,
                binding.RoutingKey,
                arguments: null,
                cancellationToken: cancellationToken);
        }

        await channel.CloseAsync(cancellationToken);
    }

    public async ValueTask DisposeAsync()
    {
        await _declarerConnections.DisposeAsync();
    }
}
