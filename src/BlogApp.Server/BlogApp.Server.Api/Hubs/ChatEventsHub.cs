using BlogApp.Server.Api.Middlewares;
using BlogApp.Server.Application.Common.Security;
using Microsoft.AspNetCore.SignalR;
using Microsoft.Extensions.Options;

namespace BlogApp.Server.Api.Hubs;

public sealed class ChatEventsHub(
    ILogger<ChatEventsHub> logger,
    IOptions<SignalRRateLimitOptions> rateLimitOptions) : RateLimitedHubBase(logger, rateLimitOptions)
{
    public async Task JoinChatSessionGroup(string sessionId)
    {
        CheckRateLimit();

        if (!Guid.TryParse(sessionId, out _))
        {
            throw new HubException("Invalid session ID format");
        }

        var tokenSessionId = Context.User?.FindFirst(ChatSessionTokenDefaults.SessionIdClaim)?.Value;
        var tokenUse = Context.User?.FindFirst(ChatSessionTokenDefaults.TokenUseClaim)?.Value;
        if (!string.Equals(tokenUse, ChatSessionTokenDefaults.TokenUseValue, StringComparison.Ordinal) ||
            !string.Equals(tokenSessionId, sessionId, StringComparison.Ordinal))
        {
            throw new HubException("Access denied.");
        }

        await Groups.AddToGroupAsync(Context.ConnectionId, $"chat_{sessionId}");
    }
}
