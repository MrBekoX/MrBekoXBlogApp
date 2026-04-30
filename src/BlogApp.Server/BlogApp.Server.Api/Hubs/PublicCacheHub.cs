using Microsoft.AspNetCore.SignalR;

namespace BlogApp.Server.Api.Hubs;

public sealed class PublicCacheHub(
    ILogger<PublicCacheHub> logger) : Hub
{
    private static readonly HashSet<string> AllowedGroups = ["posts", "categories", "tags"];

    public async Task SubscribeToGroup(string groupName)
    {
        if (!AllowedGroups.Contains(groupName))
        {
            throw new HubException($"Invalid group name. Allowed: {string.Join(", ", AllowedGroups)}");
        }

        await Groups.AddToGroupAsync(Context.ConnectionId, groupName);
        logger.LogDebug("Client {ConnectionId} subscribed to {Group}", Context.ConnectionId, groupName);
    }

    public async Task UnsubscribeFromGroup(string groupName)
    {
        if (!AllowedGroups.Contains(groupName))
        {
            throw new HubException($"Invalid group name. Allowed: {string.Join(", ", AllowedGroups)}");
        }

        await Groups.RemoveFromGroupAsync(Context.ConnectionId, groupName);
        logger.LogDebug("Client {ConnectionId} unsubscribed from {Group}", Context.ConnectionId, groupName);
    }
}
