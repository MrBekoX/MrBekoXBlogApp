namespace BlogApp.BuildingBlocks.Messaging;

/// <summary>
/// Retry the original unacknowledged delivery locally. No republish or new message
/// identity is created; the caller ACKs success or dead-letters the final failure.
/// </summary>
public static class ConsumerDeliveryRetry
{
    public static async Task ExecuteAsync(
        Func<CancellationToken, Task> handle,
        Func<Exception, bool> isRetryable,
        IReadOnlyList<TimeSpan> delays,
        CancellationToken cancellationToken)
    {
        for (var attempt = 0; ; attempt++)
        {
            cancellationToken.ThrowIfCancellationRequested();
            try
            {
                await handle(cancellationToken);
                return;
            }
            catch (Exception error) when (error is not OperationCanceledException
                                          && attempt < delays.Count && isRetryable(error))
            {
                await Task.Delay(delays[attempt], cancellationToken);
            }
        }
    }
}
