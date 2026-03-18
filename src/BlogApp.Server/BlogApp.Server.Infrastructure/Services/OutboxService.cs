using Microsoft.Extensions.Logging;
using System.Text.Json;
using System.Text.Json.Serialization;
using BlogApp.BuildingBlocks.Messaging;
using BlogApp.BuildingBlocks.Messaging.Abstractions;
using BlogApp.BuildingBlocks.Messaging.Options;
using BlogApp.BuildingBlocks.Messaging.RabbitMQ;
using BlogApp.Server.Application.Common.Interfaces.Services;
using BlogApp.Server.Domain.Entities;
using BlogApp.Server.Domain.Enums;
using BlogApp.Server.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Options;
using RabbitMQ.Client;

namespace BlogApp.Server.Infrastructure.Services;

public class OutboxService(
    AppDbContext context,
    RabbitMqConnection connection,
    IOptions<RabbitMqSettings> settings,
    ILogger<OutboxService> logger) : IOutboxService
{
    private static readonly JsonSerializerOptions SerializerOptions = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
        WriteIndented = false
    };

    private readonly RabbitMqSettings _settings = settings.Value;
    public bool IsEnabled => _settings.Enabled;

    public async Task<OutboxMessage> EnqueueAsync<TEvent>(
        TEvent @event,
        string routingKey,
        CancellationToken cancellationToken = default)
        where TEvent : IIntegrationEvent
    {
        var outboxMessage = new OutboxMessage
        {
            MessageId = @event.MessageId,
            OperationId = @event.OperationId ?? @event.MessageId.ToString(),
            CorrelationId = @event.CorrelationId,
            CausationId = @event.CausationId,
            RoutingKey = routingKey,
            EventType = @event.EventType,
            PayloadJson = JsonSerializer.Serialize(@event, @event.GetType(), SerializerOptions),
            HeadersJson = JsonSerializer.Serialize(
                new Dictionary<string, object?>
                {
                    ["messageId"] = @event.MessageId,
                    ["operationId"] = @event.OperationId,
                    ["correlationId"] = @event.CorrelationId,
                    ["causationId"] = @event.CausationId
                },
                SerializerOptions),
            Status = OutboxMessageStatus.Pending,
            NextAttemptAt = DateTime.UtcNow
        };

        context.OutboxMessages.Add(outboxMessage);
        await context.SaveChangesAsync(cancellationToken);

        return outboxMessage;
    }

    public async Task<bool> TryPublishAsync(Guid outboxMessageId, CancellationToken cancellationToken = default)
    {
        var claimed = await context.OutboxMessages
            .Where(x => x.Id == outboxMessageId && (x.Status == OutboxMessageStatus.Pending || x.Status == OutboxMessageStatus.Failed))
            .ExecuteUpdateAsync(
                setters => setters
                    .SetProperty(x => x.Status, OutboxMessageStatus.Processing)
                    .SetProperty(x => x.AttemptCount, x => x.AttemptCount + 1)
                    .SetProperty(x => x.LastError, x => null)
                    .SetProperty(x => x.UpdatedAt, x => DateTime.UtcNow),
                cancellationToken);

        if (claimed == 0)
        {
            var current = await context.OutboxMessages.AsNoTracking().SingleOrDefaultAsync(x => x.Id == outboxMessageId, cancellationToken);
            return current?.Status == OutboxMessageStatus.Published;
        }

        var outboxMessage = await context.OutboxMessages
            .AsNoTracking()
            .SingleAsync(x => x.Id == outboxMessageId, cancellationToken);

        try
        {
            await PublishRawAsync(outboxMessage, cancellationToken);

            await context.OutboxMessages
                .Where(x => x.Id == outboxMessageId)
                .ExecuteUpdateAsync(
                    setters => setters
                        .SetProperty(x => x.Status, OutboxMessageStatus.Published)
                        .SetProperty(x => x.PublishedAt, x => DateTime.UtcNow)
                        .SetProperty(x => x.LastError, x => null)
                        .SetProperty(x => x.UpdatedAt, x => DateTime.UtcNow),
                    cancellationToken);

            return true;
        }
        catch (Exception ex)
        {
            logger.LogError(ex, "Failed to publish outbox message {OutboxMessageId}", outboxMessageId);

            var nextAttemptAt = DateTime.UtcNow.AddSeconds(Math.Min(Math.Max(outboxMessage.AttemptCount, 1) * 2, 30));
            await context.OutboxMessages
                .Where(x => x.Id == outboxMessageId)
                .ExecuteUpdateAsync(
                    setters => setters
                        .SetProperty(x => x.Status, OutboxMessageStatus.Failed)
                        .SetProperty(x => x.LastError, x => ex.Message)
                        .SetProperty(x => x.NextAttemptAt, x => nextAttemptAt)
                        .SetProperty(x => x.UpdatedAt, x => DateTime.UtcNow),
                    cancellationToken);

            return false;
        }
    }

    public async Task<int> PublishPendingAsync(int batchSize, CancellationToken cancellationToken = default)
    {
        var now = DateTime.UtcNow;
        var pendingIds = await context.OutboxMessages
            .AsNoTracking()
            .Where(x =>
                (x.Status == OutboxMessageStatus.Pending || x.Status == OutboxMessageStatus.Failed) &&
                x.NextAttemptAt <= now)
            .OrderBy(x => x.CreatedAt)
            .Take(batchSize)
            .Select(x => x.Id)
            .ToListAsync(cancellationToken);

        var publishedCount = 0;
        foreach (var id in pendingIds)
        {
            if (await TryPublishAsync(id, cancellationToken))
            {
                publishedCount++;
            }
        }

        return publishedCount;
    }

    private async Task PublishRawAsync(OutboxMessage outboxMessage, CancellationToken cancellationToken)
    {
        if (!_settings.Enabled)
        {
            logger.LogDebug("RabbitMQ disabled, skipping outbox publish for {OutboxMessageId}", outboxMessage.Id);
            return;
        }

        await using var channel = await connection.CreateChannelAsync(publisherConfirms: true, cancellationToken);

        await channel.ExchangeDeclareAsync(
            exchange: MessagingConstants.ExchangeName,
            type: ExchangeType.Direct,
            durable: true,
            autoDelete: false,
            cancellationToken: cancellationToken);

        var properties = new BasicProperties
        {
            Persistent = true,
            DeliveryMode = DeliveryModes.Persistent,
            MessageId = outboxMessage.MessageId.ToString(),
            CorrelationId = outboxMessage.CorrelationId,
            ContentType = "application/json",
            Timestamp = new AmqpTimestamp(DateTimeOffset.UtcNow.ToUnixTimeSeconds()),
            Type = outboxMessage.EventType,
            Headers = new Dictionary<string, object?>
            {
                ["operationId"] = outboxMessage.OperationId,
                ["causationId"] = outboxMessage.CausationId
            }
        };

        var body = System.Text.Encoding.UTF8.GetBytes(outboxMessage.PayloadJson);

        await channel.BasicPublishAsync(
            exchange: MessagingConstants.ExchangeName,
            routingKey: outboxMessage.RoutingKey,
            mandatory: false,
            basicProperties: properties,
            body: body,
            cancellationToken: cancellationToken);
    }
}

