namespace BlogApp.Server.Application.Common.Interfaces.Services;

/// <summary>
/// Correlation service for RabbitMQ RPC pattern.
/// Handlers wait for AI generation results via correlation IDs.
/// </summary>
public interface IAiGenerationCorrelationService
{
    /// <summary>
    /// Wait for an AI generation result identified by correlation ID.
    /// Multiple callers waiting on the same correlation share the same pending result.
    /// </summary>
    Task<T> WaitForResultAsync<T>(string correlationId, TimeSpan timeout, CancellationToken ct);

    /// <summary>
    /// Complete a pending request with the AI generation result.
    /// Called by the response consumer when a result arrives from RabbitMQ.
    /// </summary>
    bool TryComplete(string correlationId, object result);
}
