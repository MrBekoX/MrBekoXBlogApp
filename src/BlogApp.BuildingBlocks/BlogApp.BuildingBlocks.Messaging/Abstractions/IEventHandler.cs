namespace BlogApp.BuildingBlocks.Messaging.Abstractions;

/// <summary>
/// Event handler interface for consuming integration events.
/// Implement this to handle specific event types from RabbitMQ.
/// </summary>
/// <typeparam name="TEvent">The event type this handler processes</typeparam>
public interface IEventHandler<in TEvent> where TEvent : IIntegrationEvent
{
    /// <summary>
    /// Handle the received event
    /// </summary>
    /// <param name="event">The event to handle</param>
    /// <param name="cancellationToken">Cancellation token</param>
    Task HandleAsync(TEvent @event, CancellationToken cancellationToken = default);
}
