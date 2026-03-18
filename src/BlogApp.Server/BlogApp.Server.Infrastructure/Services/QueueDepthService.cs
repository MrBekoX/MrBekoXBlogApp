using System.Text.Json;
using BlogApp.Server.Application.Common.Interfaces.Services;
using Microsoft.Extensions.Logging;
using StackExchange.Redis;

namespace BlogApp.Server.Infrastructure.Services;

public class QueueDepthService : IQueueDepthService
{
    private const string QueueStatsPrefix = "queue:stats";
    private const string CircuitStateKey = "queue:stats:ollama:circuit_state";
    private const int StalenessThresholdSeconds = 60;

    private readonly IConnectionMultiplexer? _redis;
    private readonly ILogger<QueueDepthService> _logger;

    public QueueDepthService(IConnectionMultiplexer? redis, ILogger<QueueDepthService> logger)
    {
        _redis = redis;
        _logger = logger;
    }

    public async Task<QueueDepthInfo> GetQueueDepthAsync(string queueName, CancellationToken ct = default)
    {
        if (_redis is null)
            return new QueueDepthInfo(0, null, true);

        try
        {
            var db = _redis.GetDatabase();
            var value = await db.StringGetAsync($"{QueueStatsPrefix}:{queueName}");
            if (value.IsNullOrEmpty)
                return new QueueDepthInfo(0, null, true);

            var doc = JsonDocument.Parse(value.ToString());
            var depth = doc.RootElement.GetProperty("depth").GetInt32();
            var updatedAt = doc.RootElement.TryGetProperty("updated_at", out var ua) ? ua.GetString() : null;

            var isStale = updatedAt is null ||
                (DateTime.UtcNow - DateTime.Parse(updatedAt)).TotalSeconds > StalenessThresholdSeconds;

            return new QueueDepthInfo(depth, updatedAt, isStale);
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Failed to read queue depth for {QueueName}", queueName);
            return new QueueDepthInfo(0, null, true);
        }
    }

    public async Task<string> GetCircuitStateAsync(CancellationToken ct = default)
    {
        if (_redis is null)
            return "unknown";

        try
        {
            var db = _redis.GetDatabase();
            var value = await db.StringGetAsync(CircuitStateKey);
            if (value.IsNullOrEmpty)
                return "unknown";

            var doc = JsonDocument.Parse(value.ToString());
            return doc.RootElement.GetProperty("state").GetString() ?? "unknown";
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Failed to read circuit state");
            return "unknown";
        }
    }
}
