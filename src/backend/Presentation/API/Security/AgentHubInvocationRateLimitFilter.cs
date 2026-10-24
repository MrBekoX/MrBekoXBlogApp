using System.Security.Claims;
using BlogApp.Presentation.Api.Helpers;
using BlogApp.Presentation.Api.Hubs;
using BlogApp.Presentation.Api.Middlewares;
using BlogApp.Presentation.Api.Services;
using Microsoft.AspNetCore.SignalR;
using Microsoft.Extensions.Options;

namespace BlogApp.Presentation.Api.Security;

/// <summary>Enforce websocket frame quotas before an agent method queries ownership.</summary>
public sealed class AgentHubInvocationRateLimitFilter(SignalRAdmissionControl admission,
    IOptions<SignalRRateLimitOptions> options) : IHubFilter
{
    private static readonly object LeaseKey = new();

    public async Task OnConnectedAsync(HubLifetimeContext context, Func<HubLifetimeContext, Task> next)
    {
        if (context.Hub is not AgentRunsHub) { await next(context); return; }
        var http = context.Context.GetHttpContext();
        var ip = http is null ? "unknown" : ClientIpAddress.Get(http) ?? "unknown";
        if (!admission.TryAcquireHubConnection(ip, options.Value, out var lease))
        {
            context.Context.Abort();
            throw new HubException("Too many agent connections. Please retry later.");
        }
        context.Context.Items[LeaseKey] = lease;
        try { await next(context); }
        catch
        {
            context.Context.Items.Remove(LeaseKey);
            lease!.Dispose();
            throw;
        }
    }
    public async ValueTask<object?> InvokeMethodAsync(HubInvocationContext invocationContext,
        Func<HubInvocationContext, ValueTask<object?>> next)
    {
        if (invocationContext.Hub is AgentRunsHub)
        {
            var context = invocationContext.Context;
            var http = context.GetHttpContext();
            var ip = http is null ? "unknown" : ClientIpAddress.Get(http) ?? "unknown";
            var owner = Owner(context.User, http) ?? "anonymous:" + ip;
            if (!admission.TryConsumeInvocation(context.ConnectionId, owner, ip, options.Value))
                throw new HubException("Agent hub invocation limit exceeded. Please retry later.");
        }
        return await next(invocationContext);
    }

    public async Task OnDisconnectedAsync(HubLifetimeContext context, Exception? exception,
        Func<HubLifetimeContext, Exception?, Task> next)
    {
        try { await next(context, exception); }
        finally
        {
            admission.ForgetConnection(context.Context.ConnectionId);
            if (context.Context.Items.Remove(LeaseKey, out var lease)) (lease as IDisposable)?.Dispose();
        }
    }

    private static string? Owner(ClaimsPrincipal? principal, HttpContext? http)
    {
        var claim = principal?.FindFirst("userId") ?? principal?.FindFirst(ClaimTypes.NameIdentifier);
        if (Guid.TryParse(claim?.Value, out var user)) return "u:" + user.ToString("D");
        var guest = http?.Request.Cookies[AgentGuestSessionService.CookieName];
        return guest is { Length: <= 64 } && Guid.TryParseExact(guest, "D", out var id) ? "g:" + id.ToString("D") : null;
    }
}
