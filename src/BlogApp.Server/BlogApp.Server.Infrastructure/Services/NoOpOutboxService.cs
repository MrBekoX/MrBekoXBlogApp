using Microsoft.Extensions.Logging;
using BlogApp.BuildingBlocks.Messaging.Abstractions;
using BlogApp.Server.Application.Common.Interfaces.Services;
using BlogApp.Server.Domain.Entities;

namespace BlogApp.Server.Infrastructure.Services;

public class NoOpOutboxService(ILogger<NoOpOutboxService> logger) : IOutboxService
{
    public bool IsEnabled => false;

    public Task<OutboxMessage> EnqueueAsync<TEvent>(TEvent @event, string routingKey, CancellationToken cancellationToken = default)
        where TEvent : IIntegrationEvent
    {
        logger.LogWarning("Outbox enqueue requested while RabbitMQ is disabled for {EventType}", @event.EventType);
        throw new InvalidOperationException("RabbitMQ outbox is disabled.");
    }

    public Task<bool> TryPublishAsync(Guid outboxMessageId, CancellationToken cancellationToken = default)
    {
        logger.LogWarning("Outbox publish requested while RabbitMQ is disabled for {OutboxMessageId}", outboxMessageId);
        return Task.FromResult(false);
    }

    public Task<int> PublishPendingAsync(int batchSize, CancellationToken cancellationToken = default)
    {
        return Task.FromResult(0);
    }
}

