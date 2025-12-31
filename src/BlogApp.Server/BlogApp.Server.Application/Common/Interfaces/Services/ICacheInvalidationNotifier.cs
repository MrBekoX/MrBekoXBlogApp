namespace BlogApp.Server.Application.Common.Interfaces.Services;

/// <summary>
/// Cache invalidation event types.
/// </summary>
public enum CacheInvalidationType
{
    /// <summary>Group version rotated - all cached items in group are stale.</summary>
    GroupRotated,
    /// <summary>Specific key removed from cache.</summary>
    KeyRemoved,
    /// <summary>All keys with prefix removed.</summary>
    PrefixRemoved
}

/// <summary>
/// Cache invalidation event payload sent to frontend clients.
/// </summary>
public record CacheInvalidationEvent(
    CacheInvalidationType Type,
    string Target,
    DateTimeOffset Timestamp
);

/// <summary>
/// Interface for notifying frontend clients about cache invalidation events.
/// Used to keep frontend cache in sync with backend cache changes.
/// </summary>
public interface ICacheInvalidationNotifier
{
    /// <summary>
    /// Notifies all connected clients that a cache group has been invalidated.
    /// </summary>
    /// <param name="groupName">The cache group name (e.g., "posts_list")</param>
    Task NotifyGroupInvalidatedAsync(string groupName, CancellationToken cancellationToken = default);

    /// <summary>
    /// Notifies all connected clients that a specific cache key has been removed.
    /// </summary>
    /// <param name="key">The cache key that was removed</param>
    Task NotifyKeyRemovedAsync(string key, CancellationToken cancellationToken = default);

    /// <summary>
    /// Notifies all connected clients that all keys with a prefix have been removed.
    /// </summary>
    /// <param name="prefix">The cache key prefix</param>
    Task NotifyPrefixRemovedAsync(string prefix, CancellationToken cancellationToken = default);

    /// <summary>
    /// Notifies clients subscribed to a specific group about cache invalidation.
    /// </summary>
    /// <param name="groupName">The SignalR group name to notify</param>
    /// <param name="cacheGroup">The cache group that was invalidated</param>
    Task NotifyGroupSubscribersAsync(string groupName, string cacheGroup, CancellationToken cancellationToken = default);
}

