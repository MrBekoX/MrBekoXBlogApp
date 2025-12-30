using BlogApp.Server.Api.Hubs;
using BlogApp.Server.Application.Common.Interfaces;
using Microsoft.AspNetCore.SignalR;

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
            _logger.LogDebug("Broadcasted cache group invalidation: {GroupName}", groupName);
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Failed to broadcast cache group invalidation: {GroupName}", groupName);
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
            _logger.LogDebug("Broadcasted cache key removal: {Key}", key);
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Failed to broadcast cache key removal: {Key}", key);
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
            _logger.LogDebug("Broadcasted cache prefix removal: {Prefix}", prefix);
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Failed to broadcast cache prefix removal: {Prefix}", prefix);
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
            _logger.LogDebug("Broadcasted cache invalidation to group {GroupName}: {CacheGroup}", groupName, cacheGroup);
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Failed to broadcast cache invalidation to group {GroupName}", groupName);
        }
    }
}
