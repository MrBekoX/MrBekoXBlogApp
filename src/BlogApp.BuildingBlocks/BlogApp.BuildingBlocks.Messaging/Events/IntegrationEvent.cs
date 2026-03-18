using BlogApp.BuildingBlocks.Messaging.Abstractions;

namespace BlogApp.BuildingBlocks.Messaging.Events;

/// <summary>
/// Base record for integration events.
/// Provides common properties required by all events.
/// Domain-specific events should inherit from this.
/// </summary>
public record IntegrationEvent : IIntegrationEvent
{
    /// <inheritdoc />
    public Guid MessageId { get; init; } = Guid.NewGuid();

    /// <inheritdoc />
    public string? OperationId { get; init; }

    /// <inheritdoc />
    public string? CorrelationId { get; init; }

    /// <inheritdoc />
    public string? CausationId { get; init; }

    /// <inheritdoc />
    public DateTime Timestamp { get; init; } = DateTime.UtcNow;

    /// <inheritdoc />
    public virtual string EventType => GetType().Name;
}
