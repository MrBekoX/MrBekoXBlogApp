namespace BlogApp.BuildingBlocks.Messaging.Abstractions;

/// <summary>
/// Generic event bus interface for publishing integration events.
/// Services implement this to publish events to message brokers.
/// </summary>
public interface IEventBus
{
    /// <summary>
    /// Publish an integration event to the message broker
    /// </summary>
    /// <typeparam name="TEvent">Event type implementing IIntegrationEvent</typeparam>
    /// <param name="event">The event to publish</param>
    /// <param name="routingKey">Routing key for message routing</param>
    /// <param name="cancellationToken">Cancellation token</param>
    Task PublishAsync<TEvent>(TEvent @event, string routingKey, CancellationToken cancellationToken = default)
        where TEvent : IIntegrationEvent;

    /// <summary>
    /// Check if the event bus is connected to the broker
    /// </summary>
    bool IsConnected { get; }
}
