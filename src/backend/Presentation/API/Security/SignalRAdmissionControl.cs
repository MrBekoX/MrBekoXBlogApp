using System.Security.Cryptography;
using System.Text;
using BlogApp.Presentation.Api.Middlewares;

namespace BlogApp.Presentation.Api.Security;

/// <summary>Single-process atomic admission. Active leases are removed on close;
/// invocation windows expire after a monotonic minute and have a hard key cap.</summary>
public sealed class SignalRAdmissionControl(TimeProvider clock)
{
    private readonly object _gate = new();
    private sealed class Connections
    {
        public Dictionary<string, int> Counts { get; } = new(StringComparer.Ordinal);
        public int Total;
    }
    private readonly Connections _transports = new();
    private readonly Connections _hubs = new();
    private readonly Dictionary<string, Window> _invocations = new(StringComparer.Ordinal);
    private long _lastSweep;
    private sealed record Window(long Started, int Count);
    public int ActiveConnectionCount { get { lock (_gate) return _transports.Total; } }
    public int ActiveHubConnectionCount { get { lock (_gate) return _hubs.Total; } }
    public int TrackedInvocationSubjectCount { get { lock (_gate) return _invocations.Count; } }

    public bool TryAcquireConnection(string ip, SignalRRateLimitOptions options, out IDisposable? lease)
        => TryAcquire(ip, options, _transports, out lease);

    // A long-polling connection survives between HTTP requests. Track the hub
    // lifecycle separately, without double-counting websocket transport leases.
    public bool TryAcquireHubConnection(string ip, SignalRRateLimitOptions options, out IDisposable? lease)
        => TryAcquire(ip, options, _hubs, out lease);

    private bool TryAcquire(string ip, SignalRRateLimitOptions options, Connections state, out IDisposable? lease)
    {
        lock (_gate)
        {
            state.Counts.TryGetValue(ip, out var count);
            if (count >= options.MaxConnectionsPerIp || state.Total >= options.MaxConnectionsTotal
                || (count == 0 && state.Counts.Count >= options.MaxTrackedSubjects))
            { lease = null; return false; }
            state.Counts[ip] = count + 1;
            state.Total++;
            lease = new ConnectionLease(this, ip, state);
            return true;
        }
    }

    private void Release(string ip, Connections state)
    {
        lock (_gate)
        {
            if (!state.Counts.TryGetValue(ip, out var count)) return;
            if (count == 1) state.Counts.Remove(ip); else state.Counts[ip] = count - 1;
            state.Total--;
        }
    }

    public bool TryConsumeInvocation(string connectionId, string ownerKey, string ip, SignalRRateLimitOptions options)
    {
        var keys = new[] { Key("connection:", connectionId), Key("owner:", ownerKey), Key("ip:", ip) };
        var now = clock.GetTimestamp();
        lock (_gate)
        {
            var sweepInterval = _invocations.Count >= options.MaxTrackedSubjects ? TimeSpan.FromSeconds(1) : TimeSpan.FromSeconds(30);
            if (clock.GetElapsedTime(_lastSweep, now) >= sweepInterval)
            {
                foreach (var key in _invocations.Where(p => Expired(p.Value, now)).Select(p => p.Key).ToArray()) _invocations.Remove(key);
                _lastSweep = now;
            }
            var missing = 0;
            foreach (var key in keys)
            {
                if (!_invocations.TryGetValue(key, out var window)) missing++;
                else if (!Expired(window, now) && window.Count >= options.MaxInvocationsPerMinute) return false;
            }
            if (_invocations.Count + missing > options.MaxTrackedSubjects) return false;
            foreach (var key in keys)
            {
                var window = _invocations.GetValueOrDefault(key);
                _invocations[key] = window is null || Expired(window, now) ? new(now, 1) : window with { Count = window.Count + 1 };
            }
            return true;
        }
    }

    public void ForgetConnection(string connectionId) { lock (_gate) _invocations.Remove(Key("connection:", connectionId)); }
    private bool Expired(Window window, long now) => clock.GetElapsedTime(window.Started, now) >= TimeSpan.FromMinutes(1);
    private static string Key(string prefix, string value) => prefix + Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(value)));
    private sealed class ConnectionLease(SignalRAdmissionControl owner, string ip, Connections state) : IDisposable
    {
        private SignalRAdmissionControl? _owner = owner;
        public void Dispose() => Interlocked.Exchange(ref _owner, null)?.Release(ip, state);
    }
}
