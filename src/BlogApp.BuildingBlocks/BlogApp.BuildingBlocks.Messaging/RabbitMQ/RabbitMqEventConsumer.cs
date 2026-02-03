using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using BlogApp.BuildingBlocks.Messaging.Abstractions;
using BlogApp.BuildingBlocks.Messaging.Options;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;
using RabbitMQ.Client;
using RabbitMQ.Client.Events;

namespace BlogApp.BuildingBlocks.Messaging.RabbitMQ;

/// <summary>
/// Configuration for a specific event consumer
/// </summary>
public class EventConsumerConfig
{
    /// <summary>
    /// Queue name to consume from
    /// </summary>
    public required string QueueName { get; init; }

    /// <summary>
    /// Routing key to bind the queue to
    /// </summary>
    public required string RoutingKey { get; init; }

    /// <summary>
    /// Event type this consumer handles
    /// </summary>
    public required Type EventType { get; init; }

    /// <summary>
    /// Handler type that processes the event
    /// </summary>
    public required Type HandlerType { get; init; }
}

/// <summary>
/// Generic RabbitMQ consumer that routes messages to IEventHandler implementations.
/// Runs as a BackgroundService and processes messages from configured queues.
/// </summary>
public class RabbitMqEventConsumer : BackgroundService
{
    private readonly RabbitMqConnection _connection;
    private readonly RabbitMqSettings _settings;
    private readonly IServiceProvider _serviceProvider;
    private readonly ILogger<RabbitMqEventConsumer> _logger;
    private readonly IReadOnlyList<EventConsumerConfig> _consumerConfigs;
    private readonly JsonSerializerOptions _jsonOptions;

    private IChannel? _channel;
    private readonly List<string> _consumerTags = [];

    public RabbitMqEventConsumer(
        RabbitMqConnection connection,
        IOptions<RabbitMqSettings> settings,
        IServiceProvider serviceProvider,
        IEnumerable<EventConsumerConfig> consumerConfigs,
        ILogger<RabbitMqEventConsumer> logger)
    {
        _connection = connection;
        _settings = settings.Value;
        _serviceProvider = serviceProvider;
        _consumerConfigs = consumerConfigs.ToList();
        _logger = logger;

        _jsonOptions = new JsonSerializerOptions
        {
            PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
            PropertyNameCaseInsensitive = true,
            DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull
        };
    }

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        if (!_settings.Enabled)
        {
            _logger.LogInformation("RabbitMQ is disabled, event consumer will not start");
            return;
        }

        if (_consumerConfigs.Count == 0)
        {
            _logger.LogInformation("No event consumers configured, skipping RabbitMQ consumer startup");
            return;
        }

        await StartConsumingAsync(stoppingToken);
    }

    private async Task StartConsumingAsync(CancellationToken stoppingToken)
    {
        try
        {
            _logger.LogInformation("Starting RabbitMQ event consumer...");

            _channel = await _connection.CreateChannelAsync(stoppingToken);

            // Set QoS prefetch to 1 for backpressure control
            await _channel.BasicQosAsync(prefetchSize: 0, prefetchCount: 1, global: false, stoppingToken);

            // Ensure exchange exists
            await _channel.ExchangeDeclareAsync(
                exchange: MessagingConstants.ExchangeName,
                type: ExchangeType.Direct,
                durable: true,
                autoDelete: false,
                cancellationToken: stoppingToken);

            // Declare DLX and DLQ
            await _channel.ExchangeDeclareAsync(
                exchange: MessagingConstants.DeadLetterExchange,
                type: ExchangeType.Fanout,
                durable: true,
                autoDelete: false,
                cancellationToken: stoppingToken);

            // Setup each consumer configuration
            foreach (var config in _consumerConfigs)
            {
                await SetupConsumerAsync(config, stoppingToken);
            }

            _logger.LogInformation(
                "RabbitMQ event consumer started, listening on {QueueCount} queue(s)",
                _consumerConfigs.Count);

            // Keep the service running
            await Task.Delay(Timeout.Infinite, stoppingToken);
        }
        catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested)
        {
            _logger.LogInformation("RabbitMQ event consumer stopping due to cancellation");
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error in RabbitMQ event consumer");
            throw;
        }
    }

    private async Task SetupConsumerAsync(EventConsumerConfig config, CancellationToken stoppingToken)
    {
        if (_channel is null)
            throw new InvalidOperationException("Channel not initialized");

        // Declare dead letter queue
        var dlqName = $"dlq.{config.QueueName.Replace("q.", "")}";
        await _channel.QueueDeclareAsync(
            queue: dlqName,
            durable: true,
            exclusive: false,
            autoDelete: false,
            cancellationToken: stoppingToken);

        await _channel.QueueBindAsync(
            queue: dlqName,
            exchange: MessagingConstants.DeadLetterExchange,
            routingKey: "",
            cancellationToken: stoppingToken);

        // Declare main queue with DLX configuration
        await _channel.QueueDeclareAsync(
            queue: config.QueueName,
            durable: true,
            exclusive: false,
            autoDelete: false,
            arguments: new Dictionary<string, object?>
            {
                ["x-dead-letter-exchange"] = MessagingConstants.DeadLetterExchange,
                ["x-queue-type"] = "quorum"
            },
            cancellationToken: stoppingToken);

        // Bind queue to exchange with routing key
        await _channel.QueueBindAsync(
            queue: config.QueueName,
            exchange: MessagingConstants.ExchangeName,
            routingKey: config.RoutingKey,
            cancellationToken: stoppingToken);

        _logger.LogInformation(
            "Bound queue {QueueName} to exchange {Exchange} with routing key {RoutingKey}",
            config.QueueName,
            MessagingConstants.ExchangeName,
            config.RoutingKey);

        // Create consumer
        var consumer = new AsyncEventingBasicConsumer(_channel);
        consumer.ReceivedAsync += async (sender, args) =>
        {
            await HandleMessageAsync(args, config);
        };

        // Start consuming
        var consumerTag = await _channel.BasicConsumeAsync(
            queue: config.QueueName,
            autoAck: false,
            consumer: consumer,
            cancellationToken: stoppingToken);

        _consumerTags.Add(consumerTag);

        _logger.LogInformation(
            "Started consuming from queue {QueueName} with consumer tag {ConsumerTag}",
            config.QueueName,
            consumerTag);
    }

    private async Task HandleMessageAsync(BasicDeliverEventArgs args, EventConsumerConfig config)
    {
        var deliveryTag = args.DeliveryTag;
        var messageId = args.BasicProperties?.MessageId ?? "unknown";
        var deliveryCount = GetDeliveryCount(args);

        try
        {
            _logger.LogDebug(
                "Received message {MessageId} from queue {QueueName} (delivery #{DeliveryCount})",
                messageId,
                config.QueueName,
                deliveryCount);

            // Deserialize event
            var body = Encoding.UTF8.GetString(args.Body.ToArray());
            var @event = JsonSerializer.Deserialize(body, config.EventType, _jsonOptions);

            if (@event is null)
            {
                _logger.LogWarning("Failed to deserialize message {MessageId}, rejecting", messageId);
                await RejectMessageAsync(deliveryTag, requeue: false);
                return;
            }

            // Create scope and resolve handler
            using var scope = _serviceProvider.CreateScope();
            var handler = scope.ServiceProvider.GetRequiredService(config.HandlerType);

            // Invoke HandleAsync via reflection
            var handleMethod = config.HandlerType.GetMethod("HandleAsync");
            if (handleMethod is null)
            {
                _logger.LogError("Handler {HandlerType} does not have HandleAsync method", config.HandlerType.Name);
                await RejectMessageAsync(deliveryTag, requeue: false);
                return;
            }

            var task = (Task?)handleMethod.Invoke(handler, [@event, CancellationToken.None]);
            if (task is not null)
            {
                await task;
            }

            // Acknowledge successful processing
            await AcknowledgeMessageAsync(deliveryTag);

            _logger.LogInformation(
                "Successfully processed message {MessageId} from queue {QueueName}",
                messageId,
                config.QueueName);
        }
        catch (JsonException ex)
        {
            _logger.LogError(ex, "Failed to parse message {MessageId}, rejecting", messageId);
            await RejectMessageAsync(deliveryTag, requeue: false);
        }
        catch (Exception ex)
        {
            _logger.LogError(
                ex,
                "Error processing message {MessageId} from queue {QueueName}",
                messageId,
                config.QueueName);

            // Retry logic: requeue if under max retries
            const int maxRetries = 5;
            if (deliveryCount < maxRetries)
            {
                _logger.LogWarning(
                    "Requeuing message {MessageId} (attempt {DeliveryCount}/{MaxRetries})",
                    messageId,
                    deliveryCount,
                    maxRetries);
                await RejectMessageAsync(deliveryTag, requeue: true);
            }
            else
            {
                _logger.LogError(
                    "Message {MessageId} exceeded max retries ({MaxRetries}), sending to DLQ",
                    messageId,
                    maxRetries);
                await RejectMessageAsync(deliveryTag, requeue: false);
            }
        }
    }

    private static int GetDeliveryCount(BasicDeliverEventArgs args)
    {
        if (args.BasicProperties?.Headers?.TryGetValue("x-delivery-count", out var count) == true)
        {
            return count switch
            {
                int intCount => intCount,
                long longCount => (int)longCount,
                _ => 1
            };
        }
        return 1;
    }

    private async Task AcknowledgeMessageAsync(ulong deliveryTag)
    {
        if (_channel is not null)
        {
            await _channel.BasicAckAsync(deliveryTag, multiple: false);
        }
    }

    private async Task RejectMessageAsync(ulong deliveryTag, bool requeue)
    {
        if (_channel is not null)
        {
            await _channel.BasicNackAsync(deliveryTag, multiple: false, requeue: requeue);
        }
    }

    public override async Task StopAsync(CancellationToken cancellationToken)
    {
        _logger.LogInformation("Stopping RabbitMQ event consumer...");

        // Cancel all consumers
        if (_channel is not null)
        {
            foreach (var consumerTag in _consumerTags)
            {
                try
                {
                    await _channel.BasicCancelAsync(consumerTag, cancellationToken: cancellationToken);
                }
                catch (Exception ex)
                {
                    _logger.LogWarning(ex, "Error cancelling consumer {ConsumerTag}", consumerTag);
                }
            }

            await _channel.CloseAsync(cancellationToken);
            _channel.Dispose();
        }

        _consumerTags.Clear();

        await base.StopAsync(cancellationToken);

        _logger.LogInformation("RabbitMQ event consumer stopped");
    }
}
