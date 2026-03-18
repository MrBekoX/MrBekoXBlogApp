using System.Text.Json;
using BlogApp.BuildingBlocks.Messaging;
using BlogApp.BuildingBlocks.Messaging.Events.Admin;
using BlogApp.Server.Application.Common.Interfaces.Services;
using BlogApp.Server.Application.Features.AdminFeature.DTOs;
using Microsoft.Extensions.Logging;

namespace BlogApp.Server.Infrastructure.Services;

public class AdminService : IAdminService
{
    private readonly IRabbitMqAdminClient _adminClient;
    private readonly ILogger<AdminService> _logger;

    public AdminService(
        IRabbitMqAdminClient adminClient,
        ILogger<AdminService> logger)
    {
        _adminClient = adminClient;
        _logger = logger;
    }

    public async Task<QuarantineStatsResponseDto> GetQuarantineStatsAsync(CancellationToken cancellationToken = default)
    {
        try
        {
            var stats = await _adminClient.GetQuarantineStatsAsync(cancellationToken);
            return stats;
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Failed to get quarantine stats");
            return new QuarantineStatsResponseDto
            {
                Ready = false,
                Queue = "q.ai.analysis.quarantine",
                Error = ex.Message
            };
        }
    }

    public async Task<QueueStatsResponseDto> GetQueueStatsAsync(CancellationToken cancellationToken = default)
    {
        try
        {
            var stats = await _adminClient.GetQueueStatsAsync(cancellationToken);
            return stats;
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Failed to get queue stats");
            return new QueueStatsResponseDto
            {
                Ready = false,
                Queue = "q.ai.analysis",
                Error = ex.Message
            };
        }
    }

    public async Task<QuarantineReplayResponseDto> ReplayQuarantineMessagesAsync(
        int maxMessages = 10,
        bool dryRun = false,
        List<string>? taxonomyPrefixes = null,
        int? maxAgeSeconds = null,
        CancellationToken cancellationToken = default)
    {
        try
        {
            var result = await _adminClient.ReplayQuarantineMessagesAsync(
                maxMessages,
                dryRun,
                taxonomyPrefixes,
                maxAgeSeconds,
                cancellationToken);
            return result;
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Failed to replay quarantine messages");
            return new QuarantineReplayResponseDto
            {
                Success = false,
                Error = ex.Message
            };
        }
    }
}
