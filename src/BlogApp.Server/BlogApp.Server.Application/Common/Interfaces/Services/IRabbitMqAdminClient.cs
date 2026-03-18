using BlogApp.Server.Application.Features.AdminFeature.DTOs;

namespace BlogApp.Server.Application.Common.Interfaces.Services;

public interface IRabbitMqAdminClient
{
    Task<QuarantineStatsResponseDto> GetQuarantineStatsAsync(CancellationToken cancellationToken = default);
    Task<QueueStatsResponseDto> GetQueueStatsAsync(CancellationToken cancellationToken = default);
    Task<QuarantineReplayResponseDto> ReplayQuarantineMessagesAsync(
        int maxMessages = 10,
        bool dryRun = false,
        List<string>? taxonomyPrefixes = null,
        int? maxAgeSeconds = null,
        CancellationToken cancellationToken = default);
}
