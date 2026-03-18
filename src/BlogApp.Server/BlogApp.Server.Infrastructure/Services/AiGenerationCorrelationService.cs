using System.Collections.Concurrent;
using System.Text.Json;
using BlogApp.Server.Application.Common.Interfaces.Services;
using Microsoft.Extensions.Logging;

namespace BlogApp.Server.Infrastructure.Services;

/// <summary>
/// Singleton correlation service for RabbitMQ RPC pattern.
/// Uses shared pending waiters so duplicate requests can await the same correlation.
/// </summary>
public class AiGenerationCorrelationService(
    ILogger<AiGenerationCorrelationService> logger) : IAiGenerationCorrelationService
{
    private static readonly JsonSerializerOptions SerializerOptions = new()
    {
        PropertyNameCaseInsensitive = true
    };

    private readonly ConcurrentDictionary<string, TaskCompletionSource<object>> _pending = new();
    private readonly ConcurrentDictionary<string, CompletedCorrelationEntry> _completed = new();

    public async Task<T> WaitForResultAsync<T>(string correlationId, TimeSpan timeout, CancellationToken ct)
    {
        CleanupExpiredCompletedEntries();

        if (_completed.TryGetValue(correlationId, out var completedEntry))
        {
            return ConvertResult<T>(completedEntry.Result);
        }

        var tcs = _pending.GetOrAdd(
            correlationId,
            _ => new TaskCompletionSource<object>(TaskCreationOptions.RunContinuationsAsynchronously));

        try
        {
            using var timeoutCts = CancellationTokenSource.CreateLinkedTokenSource(ct);
            timeoutCts.CancelAfter(timeout);

            var result = await tcs.Task.WaitAsync(timeoutCts.Token);
            return ConvertResult<T>(result);
        }
        catch (OperationCanceledException) when (!ct.IsCancellationRequested)
        {
            logger.LogWarning("AI generation timed out for correlation {CorrelationId} after {Timeout}s",
                correlationId, timeout.TotalSeconds);
            throw new TimeoutException($"AI generation timed out after {timeout.TotalSeconds}s");
        }
    }

    public bool TryComplete(string correlationId, object result)
    {
        _completed[correlationId] = new CompletedCorrelationEntry(result, DateTime.UtcNow.AddMinutes(10));

        if (_pending.TryRemove(correlationId, out var tcs))
        {
            var completed = tcs.TrySetResult(result);
            if (completed)
            {
                logger.LogDebug("Completed correlation {CorrelationId}", correlationId);
            }

            return completed;
        }

        logger.LogInformation("Stored completed result for correlation {CorrelationId} without active waiter", correlationId);
        return true;
    }

    private static T ConvertResult<T>(object result)
    {
        if (result is T typed)
        {
            return typed;
        }

        var json = JsonSerializer.Serialize(result, SerializerOptions);
        var converted = JsonSerializer.Deserialize<T>(json, SerializerOptions);
        if (converted is null)
        {
            throw new InvalidOperationException($"Unable to convert correlation result to {typeof(T).Name}.");
        }

        return converted;
    }

    private void CleanupExpiredCompletedEntries()
    {
        var now = DateTime.UtcNow;
        foreach (var kvp in _completed)
        {
            if (kvp.Value.ExpiresAtUtc <= now)
            {
                _completed.TryRemove(kvp.Key, out _);
            }
        }
    }

    private sealed record CompletedCorrelationEntry(object Result, DateTime ExpiresAtUtc);
}
