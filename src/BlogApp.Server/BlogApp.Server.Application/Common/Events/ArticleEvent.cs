using BlogApp.BuildingBlocks.Messaging;
using BlogApp.BuildingBlocks.Messaging.Events;

namespace BlogApp.Server.Application.Common.Events;

/// <summary>
/// Article payload for events
/// </summary>
public record ArticlePayload
{
    /// <summary>
    /// Article unique identifier
    /// </summary>
    public Guid ArticleId { get; init; }

    /// <summary>
    /// Article title
    /// </summary>
    public string Title { get; init; } = string.Empty;

    /// <summary>
    /// Article content (markdown)
    /// </summary>
    public string Content { get; init; } = string.Empty;

    /// <summary>
    /// Author identifier
    /// </summary>
    public Guid? AuthorId { get; init; }

    /// <summary>
    /// Normalized visibility for RAG isolation.
    /// </summary>
    public string Visibility { get; init; } = "published";

    /// <summary>
    /// Content language (tr, en, etc.)
    /// </summary>
    public string Language { get; init; } = "tr";

    /// <summary>
    /// Target region for GEO optimization (TR, US, DE, GB, etc.)
    /// </summary>
    public string TargetRegion { get; init; } = "TR";
}

/// <summary>
/// Base class for article-related events
/// </summary>
public record ArticleEvent : IntegrationEvent
{
    /// <summary>
    /// Event payload containing article data
    /// </summary>
    public ArticlePayload Payload { get; init; } = new();

    /// <summary>
    /// Get routing key for this event type
    /// </summary>
    public string GetRoutingKey() => EventType switch
    {
        MessagingConstants.RoutingKeys.ArticleCreated => MessagingConstants.RoutingKeys.ArticleCreated,
        MessagingConstants.RoutingKeys.ArticlePublished => MessagingConstants.RoutingKeys.ArticlePublished,
        MessagingConstants.RoutingKeys.ArticleUpdated => MessagingConstants.RoutingKeys.ArticleUpdated,
        _ => MessagingConstants.RoutingKeys.ArticleCreated
    };
}

/// <summary>
/// Event fired when an article is created
/// </summary>
public record ArticleCreatedEvent : ArticleEvent
{
    public override string EventType => MessagingConstants.RoutingKeys.ArticleCreated;
}

/// <summary>
/// Event fired when an article is published
/// </summary>
public record ArticlePublishedEvent : ArticleEvent
{
    public override string EventType => MessagingConstants.RoutingKeys.ArticlePublished;
}

/// <summary>
/// Event fired when an article is updated
/// </summary>
public record ArticleUpdatedEvent : ArticleEvent
{
    public override string EventType => MessagingConstants.RoutingKeys.ArticleUpdated;
}
