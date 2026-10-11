using RabbitMQ.Client;

namespace BlogApp.BuildingBlocks.Messaging;

/// <summary>Uzun ömürlü RabbitMQ bağlantısının sahibi (plan: her mesaj için yeni bağlantı açılmaz;
/// [RMQ-DOTNET#C1]). Bağlantı koptuğunda istemci otomatik recovery ile yeniden bağlanır.</summary>
public interface IRabbitMqConnectionManager : IAsyncDisposable
{
    /// <summary>Açık bağlantıyı döndürür; ilk çağrıda bağlar, sonraki çağrılarda aynı bağlantıyı paylaşır.</summary>
    Task<IConnection> GetConnectionAsync(CancellationToken cancellationToken = default);

    /// <summary>Bağlantıyı nazikçe kapatır (uygulama kapanışı).</summary>
    Task CloseAsync(CancellationToken cancellationToken = default);
}

/// <summary>Tek IConnection sahibi; publisher/consumer'lar kendi IChannel'larını bu bağlantıdan açar.</summary>
public sealed class RabbitMqConnectionManager : IRabbitMqConnectionManager
{
    private readonly RabbitMqSettings _settings;
    private readonly SemaphoreSlim _gate = new(1, 1);
    private IConnection? _connection;

    public RabbitMqConnectionManager(RabbitMqSettings settings)
    {
        _settings = settings;
    }

    public async Task<IConnection> GetConnectionAsync(CancellationToken cancellationToken = default)
    {
        if (_connection is { IsOpen: true })
        {
            return _connection;
        }

        await _gate.WaitAsync(cancellationToken);
        try
        {
            if (_connection is { IsOpen: true })
            {
                return _connection;
            }

            var factory = new ConnectionFactory
            {
                Endpoint = new AmqpTcpEndpoint(_settings.Host, _settings.Port),
                UserName = _settings.UserName,
                Password = _settings.Password,
                VirtualHost = _settings.VirtualHost,
                ClientProvidedName = _settings.ClientProvidedName,
                RequestedHeartbeat = TimeSpan.FromSeconds(_settings.RequestedHeartbeatSeconds),
                // Beklenmeyen kopmada otomatik yeniden bağlanma + topology/consumer recovery
                AutomaticRecoveryEnabled = true,
                TopologyRecoveryEnabled = true,
                NetworkRecoveryInterval = TimeSpan.FromSeconds(_settings.NetworkRecoveryIntervalSeconds),
            };

            _connection = await factory.CreateConnectionAsync(cancellationToken);
            return _connection;
        }
        finally
        {
            _gate.Release();
        }
    }

    public async Task CloseAsync(CancellationToken cancellationToken = default)
    {
        await _gate.WaitAsync(cancellationToken);
        try
        {
            if (_connection is not null)
            {
                await _connection.CloseAsync(cancellationToken: cancellationToken);
                await _connection.DisposeAsync();
                _connection = null;
            }
        }
        finally
        {
            _gate.Release();
        }
    }

    public async ValueTask DisposeAsync()
    {
        await CloseAsync();
        _gate.Dispose();
    }
}
