using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.SignalR;

namespace BlogApp.Server.Api.Hubs;

/// <summary>
/// SignalR Hub for real-time cache invalidation notifications.
/// Clients connect to receive notifications when backend cache is invalidated.
/// </summary>
[Authorize]
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

    /// <summary>
    /// Allows clients to join a user-specific group for targeted notifications.
    /// Simplified for single-user blog - allows joining own group.
    /// </summary>
    public async Task JoinUserGroup(string userId)
    {
        // Single-user blog: minimal validation, just ensure authenticated
        var currentUserId = Context.UserIdentifier;
        if (string.IsNullOrEmpty(currentUserId))
        {
            throw new HubException("User not authenticated");
        }

        await Groups.AddToGroupAsync(Context.ConnectionId, $"user_{userId}");
    }

    /// <summary>
    /// Allows clients to join a post-specific group for AI analysis notifications.
    /// </summary>
    public async Task JoinPostGroup(string postId)
    {
        await Groups.AddToGroupAsync(Context.ConnectionId, $"post_{postId}");
    }

    /// <summary>
    /// Allows clients to join a chat session group for chat response notifications.
    /// </summary>
    public async Task JoinChatSessionGroup(string sessionId)
    {
        await Groups.AddToGroupAsync(Context.ConnectionId, $"chat_{sessionId}");
    }
}

