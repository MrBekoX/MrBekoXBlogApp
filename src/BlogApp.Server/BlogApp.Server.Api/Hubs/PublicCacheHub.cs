using BlogApp.Server.Api.Middlewares;
using Microsoft.AspNetCore.SignalR;
using Microsoft.Extensions.Options;

namespace BlogApp.Server.Api.Hubs;

public sealed class PublicCacheHub(
    ILogger<PublicCacheHub> logger,
    IOptions<SignalRRateLimitOptions> rateLimitOptions) : RateLimitedHubBase(logger, rateLimitOptions)
{
    private static readonly HashSet<string> AllowedGroups = ["posts", "categories", "tags"];

    public async Task SubscribeToGroup(string groupName)
    {
        CheckRateLimit();
        if (!AllowedGroups.Contains(groupName))
        {
            throw new HubException($"Invalid group name. Allowed: {string.Join(", ", AllowedGroups)}");
        }

        await Groups.AddToGroupAsync(Context.ConnectionId, groupName);
    }

    public async Task UnsubscribeFromGroup(string groupName)
    {
        CheckRateLimit();
        if (!AllowedGroups.Contains(groupName))
        {
            throw new HubException($"Invalid group name. Allowed: {string.Join(", ", AllowedGroups)}");
        }

        await Groups.RemoveFromGroupAsync(Context.ConnectionId, groupName);
    }
}
