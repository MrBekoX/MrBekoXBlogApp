using BlogApp.Server.Api.Hubs;
using BlogApp.Server.Application.Common.Interfaces.Services;
using Microsoft.AspNetCore.SignalR;

namespace BlogApp.Server.Api.Services;

/// <summary>
/// SignalR-based implementation of cache invalidation notifier.
/// Broadcasts cache invalidation events to connected frontend clients.
/// </summary>
public class CacheInvalidationNotifier : ICacheInvalidationNotifier
{
    private readonly IHubContext<CacheInvalidationHub> _hubContext;

    public CacheInvalidationNotifier(IHubContext<CacheInvalidationHub> hubContext)
    {
        _hubContext = hubContext;
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
        catch
        {
            // Silently fail - cache invalidation is not critical
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
        catch
        {
            // Silently fail - cache invalidation is not critical
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
        catch
        {
            // Silently fail - cache invalidation is not critical
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
        catch
        {
            // Silently fail - cache invalidation is not critical
        }
    }
}

