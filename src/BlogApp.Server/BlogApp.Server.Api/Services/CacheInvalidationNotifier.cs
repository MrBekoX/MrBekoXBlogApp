using BlogApp.Server.Api.Hubs;
using BlogApp.Server.Application.Common.Interfaces.Services;
using Microsoft.AspNetCore.OutputCaching;
using Microsoft.AspNetCore.SignalR;

namespace BlogApp.Server.Api.Services;

/// <summary>
/// SignalR-based implementation of cache invalidation notifier.
/// Broadcasts cache invalidation events only to public cache subscribers.
/// </summary>
public class CacheInvalidationNotifier : ICacheInvalidationNotifier
{
    private readonly IHubContext<PublicCacheHub> _hubContext;
    private readonly IOutputCacheStore _outputCacheStore;
    private readonly ILogger<CacheInvalidationNotifier> _logger;

    public CacheInvalidationNotifier(
        IHubContext<PublicCacheHub> hubContext,
        IOutputCacheStore outputCacheStore,
        ILogger<CacheInvalidationNotifier> logger)
    {
        _hubContext = hubContext;
        _outputCacheStore = outputCacheStore;
        _logger = logger;
    }

    public async Task NotifyGroupInvalidatedAsync(string groupName, CancellationToken cancellationToken = default)
    {
        await EvictOutputCacheByTargetAsync(groupName, cancellationToken);
        await BroadcastAsync(new CacheInvalidationEvent(CacheInvalidationType.GroupRotated, groupName, DateTimeOffset.UtcNow), groupName, cancellationToken);
    }

    public async Task NotifyKeyRemovedAsync(string key, CancellationToken cancellationToken = default)
    {
        await EvictOutputCacheByTargetAsync(key, cancellationToken);
        await BroadcastAsync(new CacheInvalidationEvent(CacheInvalidationType.KeyRemoved, key, DateTimeOffset.UtcNow), key, cancellationToken);
    }

    public async Task NotifyPrefixRemovedAsync(string prefix, CancellationToken cancellationToken = default)
    {
        await EvictOutputCacheByTargetAsync(prefix, cancellationToken);
        await BroadcastAsync(new CacheInvalidationEvent(CacheInvalidationType.PrefixRemoved, prefix, DateTimeOffset.UtcNow), prefix, cancellationToken);
    }

    public async Task NotifyGroupSubscribersAsync(string groupName, string cacheGroup, CancellationToken cancellationToken = default)
    {
        await EvictOutputCacheByTargetAsync(cacheGroup, cancellationToken);

        var evt = new CacheInvalidationEvent(
            CacheInvalidationType.GroupRotated,
            cacheGroup,
            DateTimeOffset.UtcNow);

        try
        {
            await _hubContext.Clients.Group(groupName).SendAsync("CacheInvalidated", evt, cancellationToken);
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Failed to send group invalidation event to {GroupName} for {CacheGroup}", groupName, cacheGroup);
        }
    }

    private async Task BroadcastAsync(CacheInvalidationEvent evt, string target, CancellationToken cancellationToken)
    {
        var groups = ResolvePublicGroups(target);
        if (groups.Count == 0)
        {
            _logger.LogDebug("Skipping cache invalidation broadcast for non-public target {Target}", target);
            return;
        }

        foreach (var group in groups)
        {
            try
            {
                await _hubContext.Clients.Group(group).SendAsync("CacheInvalidated", evt, cancellationToken);
            }
            catch (Exception ex)
            {
                _logger.LogWarning(ex, "Failed to broadcast cache invalidation to group {Group}", group);
            }
        }
    }

    private static IReadOnlyCollection<string> ResolvePublicGroups(string target)
    {
        var targetLower = target.ToLowerInvariant();
        var groups = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

        if (targetLower.Contains("post")) groups.Add("posts");
        if (targetLower.Contains("categor")) groups.Add("categories");
        if (targetLower.Contains("tag") && !targetLower.Contains("post")) groups.Add("tags");

        return groups;
    }

    private async Task EvictOutputCacheByTargetAsync(string target, CancellationToken ct)
    {
        var targetLower = target.ToLowerInvariant();
        try
        {
            if (targetLower.Contains("post"))
                await _outputCacheStore.EvictByTagAsync("posts", ct);
            if (targetLower.Contains("categor"))
                await _outputCacheStore.EvictByTagAsync("categories", ct);
            if (targetLower.Contains("tag") && !targetLower.Contains("post"))
                await _outputCacheStore.EvictByTagAsync("tags", ct);
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Failed to evict output cache for target: {Target}", target);
        }
    }
}
