using BlogApp.Server.Api.Extensions;
using BlogApp.Server.Api.Middlewares;
using BlogApp.Server.Application.Common.Interfaces.Services;
using BlogApp.Server.Application.Common.Security;
using Microsoft.AspNetCore.SignalR;
using Microsoft.Extensions.Options;

namespace BlogApp.Server.Api.Hubs;

public sealed class AuthoringEventsHub(
    ILogger<AuthoringEventsHub> logger,
    IOptions<SignalRRateLimitOptions> rateLimitOptions,
    IPostAuthorizationService postAuthorizationService) : RateLimitedHubBase(logger, rateLimitOptions)
{
    public async Task JoinUserGroup(string userId)
    {
        CheckRateLimit();

        var currentUserId = Context.User.GetUserId();
        if (!Guid.TryParse(userId, out var requestedUserId) || currentUserId != requestedUserId)
        {
            throw new HubException("Access denied.");
        }

        await Groups.AddToGroupAsync(Context.ConnectionId, $"user_{requestedUserId}");
    }

    public async Task JoinPostGroup(string postId)
    {
        CheckRateLimit();

        if (!Guid.TryParse(postId, out var postGuid))
        {
            throw new HubException("Invalid post ID format");
        }

        var decision = await postAuthorizationService.AuthorizeAsync(
            postGuid,
            Context.User.ToPostAuthorizationSubject(),
            PostAuthorizationAction.ReceiveAiEvents,
            Context.ConnectionAborted);

        if (!decision.IsAuthorized)
        {
            throw new HubException("Access denied.");
        }

        await Groups.AddToGroupAsync(Context.ConnectionId, $"post_{postGuid}");
    }
}
