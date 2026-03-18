using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using BlogApp.BuildingBlocks.Messaging.Abstractions;
using BlogApp.BuildingBlocks.Messaging.Options;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;
using RabbitMQ.Client;
using RabbitMQ.Client.Exceptions;

namespace BlogApp.BuildingBlocks.Messaging.RabbitMQ;

/// <summary>
/// Retry policy for RabbitMQ publish operations.
/// </summary>
public class RabbitMqRetryPolicy
{
    private const int MaxRetries = 3;
    private static readonly TimeSpan[] RetryDelays =
    [
        TimeSpan.FromMilliseconds(100),
        TimeSpan.FromMilliseconds(500),
        TimeSpan.FromSeconds(1)
    ];

    public static async Task<T> ExecuteWithRetryAsync<T>(
        Func<Task<T>> operation,
        Func<Exception, bool> isTransient,
        ILogger logger,
        string operationName,
        CancellationToken cancellationToken = default)
    {
        Exception? lastException = null;

        for (int attempt = 0; attempt <= MaxRetries; attempt++)
        {
            try
            {
                if (attempt > 0)
                {
                    var delay = RetryDelays[Math.Min(attempt - 1, RetryDelays.Length - 1)];
                    logger.LogWarning("Retry attempt {Attempt}/{MaxRetries} for {Operation} after {Delay}ms",
                        attempt, MaxRetries, operationName, delay.TotalMilliseconds);
                    await Task.Delay(delay, cancellationToken);
                }

                return await operation();
            }
            catch (Exception ex) when (attempt < MaxRetries && isTransient(ex))
            {
                lastException = ex;
                logger.LogWarning(ex, "Transient error during {Operation} (attempt {Attempt}/{MaxRetries})",
                    operationName, attempt + 1, MaxRetries);
            }
        }

        throw new InvalidOperationException($"Failed to execute {operationName} after {MaxRetries} retries", lastException);
    }
}

/// <summary>
/// Generic RabbitMQ implementation of IEventBus.
/// Publishes any IIntegrationEvent to RabbitMQ.
/// </summary>
public class RabbitMqEventBus : IEventBus
{
    private readonly RabbitMqConnection _connection;
    private readonly RabbitMqSettings _settings;
    private readonly ILogger<RabbitMqEventBus> _logger;
    private readonly JsonSerializerOptions _jsonOptions;

    public RabbitMqEventBus(
        RabbitMqConnection connection,
        IOptions<RabbitMqSettings> settings,
        ILogger<RabbitMqEventBus> logger)
    {
        _connection = connection;
        _settings = settings.Value;
        _logger = logger;

        _jsonOptions = new JsonSerializerOptions
        {
            PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
            DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
            WriteIndented = false
        };
    }

    /// <inheritdoc />
    public bool IsConnected => _connection.IsConnected;

    /// <inheritdoc />
    public async Task PublishAsync<TEvent>(TEvent @event, string routingKey, CancellationToken cancellationToken = default)
        where TEvent : IIntegrationEvent
    {
        if (!_settings.Enabled)
        {
            _logger.LogDebug("RabbitMQ is disabled, skipping event publish");
            return;
        }

        await RabbitMqRetryPolicy.ExecuteWithRetryAsync(
            async () =>
            {
                await using var channel = await _connection.CreateChannelAsync(publisherConfirms: true, cancellationToken);

                await channel.ExchangeDeclareAsync(
                    exchange: MessagingConstants.ExchangeName,
                    type: ExchangeType.Direct,
                    durable: true,
                    autoDelete: false,
                    cancellationToken: cancellationToken);

                var json = JsonSerializer.Serialize(@event, @event.GetType(), _jsonOptions);
                var body = Encoding.UTF8.GetBytes(json);

                var properties = new BasicProperties
                {
                    Persistent = true,
                    DeliveryMode = DeliveryModes.Persistent,
                    MessageId = @event.MessageId.ToString(),
                    CorrelationId = @event.CorrelationId,
                    ContentType = "application/json",
                    Timestamp = new AmqpTimestamp(DateTimeOffset.UtcNow.ToUnixTimeSeconds()),
                    Type = @event.EventType,
                    Headers = new Dictionary<string, object?>
                    {
                        ["operationId"] = @event.OperationId,
                        ["causationId"] = @event.CausationId
                    }
                };

                await channel.BasicPublishAsync(
                    exchange: MessagingConstants.ExchangeName,
                    routingKey: routingKey,
                    mandatory: false,
                    basicProperties: properties,
                    body: body,
                    cancellationToken: cancellationToken);

                _logger.LogInformation(
                    "Published {EventType} event with MessageId {MessageId} to {RoutingKey} (OperationId: {OperationId})",
                    @event.EventType,
                    @event.MessageId,
                    routingKey,
                    @event.OperationId);

                return true;
            },
            ex => ex is AlreadyClosedException ||
                  ex is BrokerUnreachableException ||
                  (ex is InvalidOperationException ioe && ioe.Message.Contains("connection", StringComparison.OrdinalIgnoreCase)) ||
                  ex is TimeoutException,
            _logger,
            $"Publish {@event.EventType} event",
            cancellationToken);
    }
}

/// <summary>
/// No-op implementation of IEventBus when RabbitMQ is disabled
/// </summary>
public class NoOpEventBus : IEventBus
{
    private readonly ILogger<NoOpEventBus> _logger;

    public NoOpEventBus(ILogger<NoOpEventBus> logger)
    {
        _logger = logger;
    }

    public bool IsConnected => false;

    public Task PublishAsync<TEvent>(TEvent @event, string routingKey, CancellationToken cancellationToken = default)
        where TEvent : IIntegrationEvent
    {
        _logger.LogDebug(
            "NoOpEventBus: Skipped publishing {EventType} to {RoutingKey}",
            @event.EventType,
            routingKey);

        return Task.CompletedTask;
    }
}
