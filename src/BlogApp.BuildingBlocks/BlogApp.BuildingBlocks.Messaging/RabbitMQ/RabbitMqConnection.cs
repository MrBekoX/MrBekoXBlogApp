using BlogApp.BuildingBlocks.Messaging.Options;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;
using RabbitMQ.Client;

namespace BlogApp.BuildingBlocks.Messaging.RabbitMQ;

/// <summary>
/// Singleton wrapper for RabbitMQ connection.
/// TCP connections are expensive - reuse a single connection across the application.
/// </summary>
public sealed class RabbitMqConnection : IAsyncDisposable
{
    private readonly ILogger<RabbitMqConnection> _logger;
    private readonly RabbitMqSettings _settings;
    private IConnection? _connection;
    private bool _disposed;
    private readonly SemaphoreSlim _connectionLock = new(1, 1);

    public RabbitMqConnection(
        IOptions<RabbitMqSettings> settings,
        ILogger<RabbitMqConnection> logger)
    {
        _settings = settings.Value;
        _logger = logger;
    }

    /// <summary>
    /// Check if connection is available
    /// </summary>
    public bool IsConnected => _connection is { IsOpen: true };

    /// <summary>
    /// Get or create connection
    /// </summary>
    public async Task<IConnection> GetConnectionAsync(CancellationToken cancellationToken = default)
    {
        if (IsConnected)
            return _connection!;

        await _connectionLock.WaitAsync(cancellationToken);
        try
        {
            if (IsConnected)
                return _connection!;

            _logger.LogInformation(
                "Connecting to RabbitMQ at {Host}:{Port}",
                _settings.HostName,
                _settings.Port);

            var factory = new ConnectionFactory
            {
                HostName = _settings.HostName,
                Port = _settings.Port,
                UserName = _settings.UserName,
                Password = _settings.Password,
                VirtualHost = _settings.VirtualHost,
                // Auto recovery
                AutomaticRecoveryEnabled = true,
                NetworkRecoveryInterval = TimeSpan.FromSeconds(10),
                // Client name for management UI
                ClientProvidedName = "BlogApp.Server"
            };

            _connection = await factory.CreateConnectionAsync(cancellationToken);

            _logger.LogInformation("Connected to RabbitMQ successfully");
            return _connection;
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Failed to connect to RabbitMQ");
            throw;
        }
        finally
        {
            _connectionLock.Release();
        }
    }

    /// <summary>
    /// Create a new channel for publishing with optional publisher confirms
    /// </summary>
    public async Task<IChannel> CreateChannelAsync(bool publisherConfirms = false, CancellationToken cancellationToken = default)
    {
        var connection = await GetConnectionAsync(cancellationToken);
        var options = new CreateChannelOptions(
            publisherConfirmationsEnabled: publisherConfirms,
            publisherConfirmationTrackingEnabled: publisherConfirms
        );
        return await connection.CreateChannelAsync(options, cancellationToken);
    }

    public async ValueTask DisposeAsync()
    {
        if (_disposed)
            return;

        _disposed = true;

        // Fix Race Condition: Use lock to prevent concurrent disposal
        await _connectionLock.WaitAsync();
        try
        {
            if (_connection is not null)
            {
                if (_connection.IsOpen)
                {
                    await _connection.CloseAsync();
                }
                _connection.Dispose();
                _connection = null;
            }
        }
        finally
        {
            _connectionLock.Release();
            _connectionLock.Dispose();
        }
        _logger.LogInformation("RabbitMQ connection disposed");
    }
}
