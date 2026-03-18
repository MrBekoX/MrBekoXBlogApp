using BlogApp.BuildingBlocks.Messaging.Options;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;
using RabbitMQ.Client;

namespace BlogApp.BuildingBlocks.Messaging.RabbitMQ;

/// <summary>
/// Singleton wrapper for RabbitMQ connection with health monitoring and auto-reconnection.
/// TCP connections are expensive - reuse a single connection across the application.
/// </summary>
public sealed class RabbitMqConnection : IAsyncDisposable
{
    private readonly ILogger<RabbitMqConnection> _logger;
    private readonly RabbitMqSettings _settings;
    private IConnection? _connection;
    private bool _disposed;
    private readonly SemaphoreSlim _connectionLock = new(1, 1);

    // Health monitoring
    private readonly System.Threading.Timer _healthCheckTimer;
    private int _unhealthyCount;
    private const int MaxUnhealthyCount = 3;

    public RabbitMqConnection(
        IOptions<RabbitMqSettings> settings,
        ILogger<RabbitMqConnection> logger)
    {
        _settings = settings.Value;
        _logger = logger;

        // Start health check timer (every 30 seconds)
        _healthCheckTimer = new Timer(
            CheckConnectionHealth,
            null,
            TimeSpan.FromSeconds(30),
            TimeSpan.FromSeconds(30));
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

                // KRİTİK: Heartbeat ile dead connection tespiti
                RequestedHeartbeat = TimeSpan.FromSeconds(30),

                // Client name for management UI
                ClientProvidedName = "BlogApp.Server"
            };

            _connection = await factory.CreateConnectionAsync(cancellationToken);
            _unhealthyCount = 0; // Reset unhealthy count on successful connection

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

    /// <summary>
    /// Health check callback - periodically called by timer
    /// </summary>
    private async void CheckConnectionHealth(object? state)
    {
        try
        {
            if (_connection is null || !_connection.IsOpen)
            {
                _unhealthyCount++;
                _logger.LogWarning(
                    "Connection health check failed (attempt {Count}/{Max})",
                    _unhealthyCount,
                    MaxUnhealthyCount);

                if (_unhealthyCount >= MaxUnhealthyCount)
                {
                    _logger.LogError("Connection unhealthy, forcing reconnection");
                    await ForceReconnectAsync();
                }
                return;
            }

            // Reset counter on healthy connection
            _unhealthyCount = 0;
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error during connection health check");
        }
    }

    /// <summary>
    /// Force reconnection by closing existing connection and creating new one
    /// </summary>
    private async Task ForceReconnectAsync()
    {
        await _connectionLock.WaitAsync();
        try
        {
            // Close existing connection
            if (_connection is not null)
            {
                try
                {
                    if (_connection.IsOpen)
                    {
                        await _connection.CloseAsync();
                    }
                    _connection.Dispose();
                }
                catch (Exception ex)
                {
                    _logger.LogWarning(ex, "Error closing old connection");
                }
                _connection = null;
            }

            // Create new connection
            _logger.LogInformation("Creating new RabbitMQ connection");
            _unhealthyCount = 0;

            var factory = new ConnectionFactory
            {
                HostName = _settings.HostName,
                Port = _settings.Port,
                UserName = _settings.UserName,
                Password = _settings.Password,
                VirtualHost = _settings.VirtualHost,
                AutomaticRecoveryEnabled = true,
                NetworkRecoveryInterval = TimeSpan.FromSeconds(10),
                RequestedHeartbeat = TimeSpan.FromSeconds(30),
                ClientProvidedName = "BlogApp.Server"
            };

            _connection = await factory.CreateConnectionAsync();

            _logger.LogInformation("RabbitMQ connection re-established successfully");
        }
        finally
        {
            _connectionLock.Release();
        }
    }

    public async ValueTask DisposeAsync()
    {
        if (_disposed)
            return;

        _disposed = true;

        // Stop health check timer
        _healthCheckTimer?.Dispose();

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
