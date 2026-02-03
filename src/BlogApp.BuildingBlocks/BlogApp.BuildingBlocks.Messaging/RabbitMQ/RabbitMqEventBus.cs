using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using BlogApp.BuildingBlocks.Messaging.Abstractions;
using BlogApp.BuildingBlocks.Messaging.Options;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;
using RabbitMQ.Client;

namespace BlogApp.BuildingBlocks.Messaging.RabbitMQ;

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

        try
        {
            // Create channel for this publish (channels are cheap, connections are not)
            await using var channel = await _connection.CreateChannelAsync(cancellationToken);

            // Ensure exchange exists (idempotent declaration)
            await channel.ExchangeDeclareAsync(
                exchange: MessagingConstants.ExchangeName,
                type: ExchangeType.Direct,
                durable: true,
                autoDelete: false,
                cancellationToken: cancellationToken);

            // Serialize event to JSON
            var json = JsonSerializer.Serialize(@event, @event.GetType(), _jsonOptions);
            var body = Encoding.UTF8.GetBytes(json);

            // Set message properties for guaranteed delivery
            var properties = new BasicProperties
            {
                // Persist message to disk
                Persistent = true,
                DeliveryMode = DeliveryModes.Persistent,
                // Message metadata
                MessageId = @event.MessageId.ToString(),
                CorrelationId = @event.CorrelationId,
                ContentType = "application/json",
                Timestamp = new AmqpTimestamp(DateTimeOffset.UtcNow.ToUnixTimeSeconds()),
                // Type identifier
                Type = @event.EventType
            };

            // Publish message
            await channel.BasicPublishAsync(
                exchange: MessagingConstants.ExchangeName,
                routingKey: routingKey,
                mandatory: false,
                basicProperties: properties,
                body: body,
                cancellationToken: cancellationToken);

            _logger.LogInformation(
                "Published {EventType} event with MessageId {MessageId} to {RoutingKey}",
                @event.EventType,
                @event.MessageId,
                routingKey);
        }
        catch (Exception ex)
        {
            _logger.LogError(
                ex,
                "Failed to publish {EventType} event with MessageId {MessageId}",
                @event.EventType,
                @event.MessageId);

            // Don't throw - event publishing should not break the main flow
        }
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
