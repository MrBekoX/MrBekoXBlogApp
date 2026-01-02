using System.Diagnostics;
using System.Diagnostics.Metrics;

namespace BlogApp.Server.Infrastructure.Services;

/// <summary>
/// Provides cache-related metrics for observability.
/// Uses System.Diagnostics.Metrics for OpenTelemetry compatibility.
/// Supports L1 (in-memory) and L2 (distributed) cache layer tracking.
/// </summary>
public sealed class CacheMetrics : IDisposable
{
    private readonly Meter _meter;

    // Counters - L1 (in-memory) cache
    private readonly Counter<long> _l1Hits;
    private readonly Counter<long> _l1Misses;

    // Counters - L2 (distributed) cache
    private readonly Counter<long> _l2Hits;
    private readonly Counter<long> _l2Misses;

    // Counters - General
    private readonly Counter<long> _cacheWrites;
    private readonly Counter<long> _cacheRemovals;
    private readonly Counter<long> _cacheStampedePrevented;
    private readonly Counter<long> _cacheLockTimeouts;
    private readonly Counter<long> _cacheErrors;
    private readonly Counter<long> _l1Promotions;

    // Counters - SWR (Stale-While-Revalidate)
    private readonly Counter<long> _swrStaleHits;
    private readonly Counter<long> _swrFreshHits;
    private readonly Counter<long> _swrBackgroundRefreshes;
    private readonly Counter<long> _swrBackgroundRefreshErrors;

    // Histograms
    private readonly Histogram<double> _cacheOperationDuration;

    // Observable gauges (registered via callbacks)
    private int _trackedKeysCount;
    private int _activeLocksCount;
    private int _l1KeysCount;

    public const string MeterName = "BlogApp.Cache";

    public CacheMetrics(IMeterFactory? meterFactory = null)
    {
        _meter = meterFactory?.Create(MeterName) ?? new Meter(MeterName, "1.0.0");

        // L1 (in-memory) cache counters
        
        _l1Hits = _meter.CreateCounter<long>(
            "cache.l1.hits",
            unit: "{hit}",
            description: "Number of L1 (in-memory) cache hits");

        _l1Misses = _meter.CreateCounter<long>(
            "cache.l1.misses",
            unit: "{miss}",
            description: "Number of L1 (in-memory) cache misses");

        // L2 (distributed) cache counters
        _l2Hits = _meter.CreateCounter<long>(
            "cache.l2.hits",
            unit: "{hit}",
            description: "Number of L2 (distributed) cache hits");

        _l2Misses = _meter.CreateCounter<long>(
            "cache.l2.misses",
            unit: "{miss}",
            description: "Number of L2 (distributed) cache misses");

        // L1 promotions (L2 hit promoted to L1)
        _l1Promotions = _meter.CreateCounter<long>(
            "cache.l1.promotions",
            unit: "{promotion}",
            description: "Number of items promoted from L2 to L1");

        _cacheWrites = _meter.CreateCounter<long>(
            "cache.writes",
            unit: "{write}",
            description: "Number of cache write operations");

        _cacheRemovals = _meter.CreateCounter<long>(
            "cache.removals",
            unit: "{removal}",
            description: "Number of cache removal operations");

        _cacheStampedePrevented = _meter.CreateCounter<long>(
            "cache.stampede_prevented",
            unit: "{prevention}",
            description: "Number of cache stampedes prevented by locking");

        _cacheLockTimeouts = _meter.CreateCounter<long>(
            "cache.lock_timeouts",
            unit: "{timeout}",
            description: "Number of lock acquisition timeouts");

        _cacheErrors = _meter.CreateCounter<long>(
            "cache.errors",
            unit: "{error}",
            description: "Number of cache operation errors");

        // SWR (Stale-While-Revalidate) counters
        _swrStaleHits = _meter.CreateCounter<long>(
            "cache.swr.stale_hits",
            unit: "{hit}",
            description: "Number of stale cache hits (data returned but refresh triggered)");

        _swrFreshHits = _meter.CreateCounter<long>(
            "cache.swr.fresh_hits",
            unit: "{hit}",
            description: "Number of fresh cache hits (no refresh needed)");

        _swrBackgroundRefreshes = _meter.CreateCounter<long>(
            "cache.swr.background_refreshes",
            unit: "{refresh}",
            description: "Number of background refresh operations started");

        _swrBackgroundRefreshErrors = _meter.CreateCounter<long>(
            "cache.swr.background_refresh_errors",
            unit: "{error}",
            description: "Number of background refresh operations that failed");

        // Initialize histogram for operation duration
        _cacheOperationDuration = _meter.CreateHistogram<double>(
            "cache.operation.duration",
            unit: "ms",
            description: "Duration of cache operations in milliseconds");

        // Observable gauges for current state
        _meter.CreateObservableGauge(
            "cache.tracked_keys",
            () => _trackedKeysCount,
            unit: "{key}",
            description: "Current number of tracked L2 cache keys");

        _meter.CreateObservableGauge(
            "cache.l1.keys",
            () => _l1KeysCount,
            unit: "{key}",
            description: "Approximate number of L1 cache keys");

        _meter.CreateObservableGauge(
            "cache.active_locks",
            () => _activeLocksCount,
            unit: "{lock}",
            description: "Current number of active cache locks");
    }

    /// <summary>
    /// Records an L1 (in-memory) cache hit.
    /// </summary>
    public void RecordL1Hit(string keyPrefix)
    {
        _l1Hits.Add(1, new KeyValuePair<string, object?>("key_prefix", keyPrefix));
    }

    /// <summary>
    /// Records an L1 (in-memory) cache miss.
    /// </summary>
    public void RecordL1Miss(string keyPrefix)
    {
        _l1Misses.Add(1, new KeyValuePair<string, object?>("key_prefix", keyPrefix));
    }

    /// <summary>
    /// Records an L2 (distributed) cache hit.
    /// </summary>
    public void RecordL2Hit(string keyPrefix)
    {
        _l2Hits.Add(1, new KeyValuePair<string, object?>("key_prefix", keyPrefix));
    }

    /// <summary>
    /// Records an L2 (distributed) cache miss.
    /// </summary>
    public void RecordL2Miss(string keyPrefix)
    {
        _l2Misses.Add(1, new KeyValuePair<string, object?>("key_prefix", keyPrefix));
    }

    /// <summary>
    /// Records a promotion from L2 to L1.
    /// </summary>
    public void RecordL1Promotion(string keyPrefix)
    {
        _l1Promotions.Add(1, new KeyValuePair<string, object?>("key_prefix", keyPrefix));
    }

    #region SWR (Stale-While-Revalidate) Metrics

    /// <summary>
    /// Records a stale cache hit (data returned but background refresh triggered).
    /// </summary>
    public void RecordSwrStaleHit(string keyPrefix)
    {
        _swrStaleHits.Add(1, new KeyValuePair<string, object?>("key_prefix", keyPrefix));
    }

    /// <summary>
    /// Records a fresh cache hit (no refresh needed).
    /// </summary>
    public void RecordSwrFreshHit(string keyPrefix)
    {
        _swrFreshHits.Add(1, new KeyValuePair<string, object?>("key_prefix", keyPrefix));
    }

    /// <summary>
    /// Records a background refresh operation being started.
    /// </summary>
    public void RecordSwrBackgroundRefresh(string keyPrefix)
    {
        _swrBackgroundRefreshes.Add(1, new KeyValuePair<string, object?>("key_prefix", keyPrefix));
    }

    /// <summary>
    /// Records a background refresh operation failure.
    /// </summary>
    public void RecordSwrBackgroundRefreshError(string keyPrefix)
    {
        _swrBackgroundRefreshErrors.Add(1, new KeyValuePair<string, object?>("key_prefix", keyPrefix));
    }

    #endregion

    /// <summary>
    /// Records a cache write operation.
    /// </summary>
    public void RecordWrite(string keyPrefix)
    {
        _cacheWrites.Add(1, new KeyValuePair<string, object?>("key_prefix", keyPrefix));
    }

    /// <summary>
    /// Records a cache removal operation.
    /// </summary>
    public void RecordRemoval(string keyPrefix)
    {
        _cacheRemovals.Add(1, new KeyValuePair<string, object?>("key_prefix", keyPrefix));
    }

    /// <summary>
    /// Records a prevented cache stampede (double-check hit after lock).
    /// </summary>
    public void RecordStampedePrevented(string keyPrefix)
    {
        _cacheStampedePrevented.Add(1, new KeyValuePair<string, object?>("key_prefix", keyPrefix));
    }

    /// <summary>
    /// Records a lock timeout occurrence.
    /// </summary>
    public void RecordLockTimeout(string keyPrefix)
    {
        _cacheLockTimeouts.Add(1, new KeyValuePair<string, object?>("key_prefix", keyPrefix));
    }

    /// <summary>
    /// Records a cache operation error.
    /// </summary>
    public void RecordError(string operation, string keyPrefix)
    {
        _cacheErrors.Add(1,
            new KeyValuePair<string, object?>("operation", operation),
            new KeyValuePair<string, object?>("key_prefix", keyPrefix));
    }

    /// <summary>
    /// Records the duration of a cache operation.
    /// </summary>
    public void RecordOperationDuration(string operation, string keyPrefix, double durationMs)
    {
        _cacheOperationDuration.Record(durationMs,
            new KeyValuePair<string, object?>("operation", operation),
            new KeyValuePair<string, object?>("key_prefix", keyPrefix));
    }

    /// <summary>
    /// Updates the tracked L2 keys count for the observable gauge.
    /// </summary>
    public void UpdateTrackedKeysCount(int count)
    {
        _trackedKeysCount = count;
    }

    /// <summary>
    /// Updates the L1 keys count for the observable gauge.
    /// </summary>
    public void UpdateL1KeysCount(int count)
    {
        _l1KeysCount = count;
    }

    /// <summary>
    /// Updates the active locks count for the observable gauge.
    /// </summary>
    public void UpdateActiveLocksCount(int count)
    {
        _activeLocksCount = count;
    }

    /// <summary>
    /// Creates a scope that automatically records operation duration.
    /// </summary>
    public OperationScope StartOperation(string operation, string key)
    {
        return new OperationScope(this, operation, key);
    }

    public void Dispose()
    {
        _meter.Dispose();
    }

    /// <summary>
    /// A disposable scope that records operation duration on disposal.
    /// </summary>
    public readonly struct OperationScope : IDisposable
    {
        private readonly CacheMetrics _metrics;
        private readonly string _operation;
        private readonly string _keyPrefix;
        private readonly long _startTimestamp;

        internal OperationScope(CacheMetrics metrics, string operation, string key)
        {
            _metrics = metrics;
            _operation = operation;
            _keyPrefix = ExtractKeyPrefix(key);
            _startTimestamp = Stopwatch.GetTimestamp();
        }

        public void Dispose()
        {
            var elapsed = Stopwatch.GetElapsedTime(_startTimestamp);
            _metrics.RecordOperationDuration(_operation, _keyPrefix, elapsed.TotalMilliseconds);
        }

        private static string ExtractKeyPrefix(string key)
        {
            if (string.IsNullOrEmpty(key))
                return "unknown";

            // Extract prefix before first colon (e.g., "post:slug:xyz" -> "post")
            var colonIndex = key.IndexOf(':');
            return colonIndex > 0 ? key[..colonIndex] : key;
        }
    }
}

/// <summary>
/// Extension methods for extracting key prefix from cache keys.
/// </summary>
public static class CacheKeyExtensions
{
    /// <summary>
    /// Extracts the prefix from a cache key for metric tagging.
    /// </summary>
    public static string GetKeyPrefix(this string key)
    {
        if (string.IsNullOrEmpty(key))
            return "unknown";

        var colonIndex = key.IndexOf(':');
        return colonIndex > 0 ? key[..colonIndex] : key;
    }
}
