namespace BlogApp.Server.Application.Common;

/// <summary>
/// Ambient context that signals whether the current execution flow is a
/// SWR background refresh. When true, CachingBehavior skips cache lookup
/// and delegates directly to the next pipeline step, allowing the handler
/// to execute and produce fresh data.
///
/// Uses AsyncLocal to flow correctly through Task.Run and async/await chains
/// without leaking to unrelated concurrent requests (copy-on-write semantics).
/// </summary>
public static class SwrRefreshContext
{
    private static readonly AsyncLocal<bool> _isBackgroundRefresh = new();

    public static bool IsBackgroundRefresh
    {
        get => _isBackgroundRefresh.Value;
        set => _isBackgroundRefresh.Value = value;
    }
}
