using Microsoft.AspNetCore.SignalR;

namespace BlogApp.Server.Api.Hubs;

/// <summary>
/// SignalR Hub for real-time cache invalidation notifications.
/// Clients connect to receive notifications when backend cache is invalidated.
/// </summary>
public class CacheInvalidationHub : Hub
{
    public override async Task OnConnectedAsync()
    {
        await base.OnConnectedAsync();
    }

    public override async Task OnDisconnectedAsync(Exception? exception)
    {
        await base.OnDisconnectedAsync(exception);
    }

    /// <summary>
    /// Allows clients to subscribe to specific cache groups (e.g., "posts", "categories").
    /// </summary>
    public async Task SubscribeToGroup(string groupName)
    {
        await Groups.AddToGroupAsync(Context.ConnectionId, groupName);
    }

    /// <summary>
    /// Allows clients to unsubscribe from specific cache groups.
    /// </summary>
    public async Task UnsubscribeFromGroup(string groupName)
    {
        await Groups.RemoveFromGroupAsync(Context.ConnectionId, groupName);
    }
}

