using BlogApp.Server.Api.Hubs;
using BlogApp.Server.Application.Common.Interfaces.Services;
using Microsoft.AspNetCore.SignalR;
using Microsoft.Extensions.Logging;

namespace BlogApp.Server.Api.Services;

/// <summary>
/// SignalR-based implementation of cache invalidation notifier.
/// Broadcasts cache invalidation events to connected frontend clients.
/// </summary>
public class CacheInvalidationNotifier : ICacheInvalidationNotifier
{
    private readonly IHubContext<CacheInvalidationHub> _hubContext;
    private readonly ILogger<CacheInvalidationNotifier> _logger;

    public CacheInvalidationNotifier(
        IHubContext<CacheInvalidationHub> hubContext,
        ILogger<CacheInvalidationNotifier> logger)
    {
        _hubContext = hubContext;
        _logger = logger;
    }

    public async Task NotifyGroupInvalidatedAsync(string groupName, CancellationToken cancellationToken = default)
    {
        var evt = new CacheInvalidationEvent(
            CacheInvalidationType.GroupRotated,
            groupName,
            DateTimeOffset.UtcNow
        );

        try
        {
            await _hubContext.Clients.All.SendAsync("CacheInvalidated", evt, cancellationToken);
        }
        catch (Exception ex)
        {
            // BUG-005: Add structured logging - cache invalidation is not critical but failures should be observable
            _logger.LogWarning(ex, "Failed to broadcast group invalidation event for {GroupName}", groupName);
        }
    }

    public async Task NotifyKeyRemovedAsync(string key, CancellationToken cancellationToken = default)
    {
        var evt = new CacheInvalidationEvent(
            CacheInvalidationType.KeyRemoved,
            key,
            DateTimeOffset.UtcNow
        );

        try
        {
            await _hubContext.Clients.All.SendAsync("CacheInvalidated", evt, cancellationToken);
        }
        catch (Exception ex)
        {
            // BUG-005: Add structured logging - cache invalidation is not critical but failures should be observable
            _logger.LogWarning(ex, "Failed to broadcast key removal event for {Key}", key);
        }
    }

    public async Task NotifyPrefixRemovedAsync(string prefix, CancellationToken cancellationToken = default)
    {
        var evt = new CacheInvalidationEvent(
            CacheInvalidationType.PrefixRemoved,
            prefix,
            DateTimeOffset.UtcNow
        );

        try
        {
            await _hubContext.Clients.All.SendAsync("CacheInvalidated", evt, cancellationToken);
        }
        catch (Exception ex)
        {
            // BUG-005: Add structured logging - cache invalidation is not critical but failures should be observable
            _logger.LogWarning(ex, "Failed to broadcast prefix removal event for {Prefix}", prefix);
        }
    }

    public async Task NotifyGroupSubscribersAsync(string groupName, string cacheGroup, CancellationToken cancellationToken = default)
    {
        var evt = new CacheInvalidationEvent(
            CacheInvalidationType.GroupRotated,
            cacheGroup,
            DateTimeOffset.UtcNow
        );

        try
        {
            await _hubContext.Clients.Group(groupName).SendAsync("CacheInvalidated", evt, cancellationToken);
        }
        catch (Exception ex)
        {
            // BUG-005: Add structured logging - cache invalidation is not critical but failures should be observable
            _logger.LogWarning(ex, "Failed to send group invalidation event to {GroupName} for {CacheGroup}", groupName, cacheGroup);
        }
    }
}

