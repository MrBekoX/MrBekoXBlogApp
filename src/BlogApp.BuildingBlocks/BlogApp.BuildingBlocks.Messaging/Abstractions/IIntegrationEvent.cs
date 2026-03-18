namespace BlogApp.BuildingBlocks.Messaging.Abstractions;

/// <summary>
/// Base interface for all integration events.
/// Integration events are used for async communication between services.
/// </summary>
public interface IIntegrationEvent
{
    /// <summary>
    /// Unique message identifier for transport-level idempotency.
    /// </summary>
    Guid MessageId { get; }

    /// <summary>
    /// Business operation identifier propagated end-to-end.
    /// </summary>
    string? OperationId { get; }

    /// <summary>
    /// Correlation ID for distributed tracing.
    /// </summary>
    string? CorrelationId { get; }

    /// <summary>
    /// Causation ID for tracing the triggering request or message.
    /// </summary>
    string? CausationId { get; }

    /// <summary>
    /// Event timestamp in UTC.
    /// </summary>
    DateTime Timestamp { get; }

    /// <summary>
    /// Event type identifier (e.g., "ArticlePublished").
    /// </summary>
    string EventType { get; }
}
