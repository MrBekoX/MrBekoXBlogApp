namespace BlogApp.Server.Application.Common.Interfaces.Services;

public record QueueDepthInfo(int Depth, string? UpdatedAt, bool IsStale);

public interface IQueueDepthService
{
    Task<QueueDepthInfo> GetQueueDepthAsync(string queueName, CancellationToken ct = default);
    Task<string> GetCircuitStateAsync(CancellationToken ct = default);
}
