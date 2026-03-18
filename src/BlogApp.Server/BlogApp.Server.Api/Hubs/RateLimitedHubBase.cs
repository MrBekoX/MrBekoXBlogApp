using System.Collections.Concurrent;
using System.Timers;
using BlogApp.Server.Api.Middlewares;
using Microsoft.AspNetCore.SignalR;
using Microsoft.Extensions.Options;
using Timer = System.Timers.Timer;
using ElapsedEventArgs = System.Timers.ElapsedEventArgs;

namespace BlogApp.Server.Api.Hubs;

public abstract class RateLimitedHubBase : Hub
{
    private static readonly ConcurrentDictionary<string, InvocationTracker> InvocationTrackers = new();
    private static readonly Timer CleanupTimer = new(TimeSpan.FromMinutes(1));

    private readonly ILogger _logger;
    private readonly IOptions<SignalRRateLimitOptions> _rateLimitOptions;

    static RateLimitedHubBase()
    {
        CleanupTimer.Elapsed += CleanupInvocationTrackers;
        CleanupTimer.AutoReset = true;
        CleanupTimer.Start();
    }

    protected RateLimitedHubBase(ILogger logger, IOptions<SignalRRateLimitOptions> rateLimitOptions)
    {
        _logger = logger;
        _rateLimitOptions = rateLimitOptions;
    }

    protected void CheckRateLimit()
    {
        var tracker = InvocationTrackers.GetOrAdd(Context.ConnectionId, _ => new InvocationTracker());
        var count = tracker.Increment();
        if (count > _rateLimitOptions.Value.MaxInvocationsPerMinute)
        {
            _logger.LogWarning(
                "Rate limit exceeded for hub {Hub} connection {ConnectionId}: {Count}/{Max}",
                GetType().Name,
                Context.ConnectionId,
                count,
                _rateLimitOptions.Value.MaxInvocationsPerMinute);
            throw new HubException("Rate limit exceeded. Please slow down.");
        }
    }

    protected string GetClientIp() =>
        Context.GetHttpContext()?.Connection?.RemoteIpAddress?.ToString() ?? "unknown";

    public override async Task OnConnectedAsync()
    {
        _logger.LogInformation(
            "{Hub} client {ConnectionId} connected from {IP}",
            GetType().Name,
            Context.ConnectionId,
            GetClientIp());
        await base.OnConnectedAsync();
    }

    public override async Task OnDisconnectedAsync(Exception? exception)
    {
        InvocationTrackers.TryRemove(Context.ConnectionId, out _);
        _logger.LogInformation(
            "{Hub} client {ConnectionId} disconnected from {IP}",
            GetType().Name,
            Context.ConnectionId,
            GetClientIp());
        await base.OnDisconnectedAsync(exception);
    }

    private static void CleanupInvocationTrackers(object? sender, ElapsedEventArgs e)
    {
        var cutoff = DateTimeOffset.UtcNow.AddMinutes(-1);
        foreach (var kvp in InvocationTrackers)
        {
            if (kvp.Value.LastReset < cutoff)
            {
                InvocationTrackers.TryRemove(kvp.Key, out _);
            }
        }
    }

    private sealed class InvocationTracker
    {
        private int _count;

        public DateTimeOffset LastReset { get; private set; } = DateTimeOffset.UtcNow;

        public int Increment()
        {
            if (LastReset < DateTimeOffset.UtcNow.AddMinutes(-1))
            {
                _count = 0;
                LastReset = DateTimeOffset.UtcNow;
            }

            return Interlocked.Increment(ref _count);
        }
    }
}
