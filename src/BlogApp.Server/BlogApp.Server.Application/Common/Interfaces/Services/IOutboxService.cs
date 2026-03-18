using BlogApp.BuildingBlocks.Messaging.Abstractions;
using BlogApp.Server.Domain.Entities;

namespace BlogApp.Server.Application.Common.Interfaces.Services;

public interface IOutboxService
{
    bool IsEnabled { get; }

    Task<OutboxMessage> EnqueueAsync<TEvent>(TEvent @event, string routingKey, CancellationToken cancellationToken = default)
        where TEvent : IIntegrationEvent;

    Task<bool> TryPublishAsync(Guid outboxMessageId, CancellationToken cancellationToken = default);
    Task<int> PublishPendingAsync(int batchSize, CancellationToken cancellationToken = default);
}
