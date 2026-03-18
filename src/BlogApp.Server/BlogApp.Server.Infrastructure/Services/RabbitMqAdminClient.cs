using System.Text.Json;
using BlogApp.BuildingBlocks.Messaging;
using BlogApp.BuildingBlocks.Messaging.RabbitMQ;
using BlogApp.Server.Application.Common.Interfaces.Services;
using BlogApp.Server.Application.Features.AdminFeature.DTOs;
using Microsoft.Extensions.Logging;
using RabbitMQ.Client;

namespace BlogApp.Server.Infrastructure.Services;

/// <summary>
/// RabbitMQ admin client for queue management operations.
/// Communicates with AI Agent via RabbitMQ for quarantine and queue operations.
/// </summary>
public class RabbitMqAdminClient : IRabbitMqAdminClient
{
    private readonly RabbitMqConnection _connection;
    private readonly ILogger<RabbitMqAdminClient> _logger;

    private const string ExchangeName = "blog.events";
    private const string AdminExchangeName = "blog.admin";
    private const string QuarantineQueue = "q.ai.analysis.quarantine";
    private const string MainQueue = "q.ai.analysis";
    private const string QuarantineExchange = "quarantine.blog";

    public RabbitMqAdminClient(
        RabbitMqConnection connection,
        ILogger<RabbitMqAdminClient> logger)
    {
        _connection = connection;
        _logger = logger;
    }

    public async Task<QuarantineStatsResponseDto> GetQuarantineStatsAsync(CancellationToken cancellationToken = default)
    {
        try
        {
            var channel = await _connection.CreateChannelAsync(cancellationToken: cancellationToken);
            try
            {
                var declare = await channel.QueueDeclarePassiveAsync(QuarantineQueue, cancellationToken: cancellationToken);
                return new QuarantineStatsResponseDto
                {
                    Ready = true,
                    Queue = QuarantineQueue,
                    RoutingKey = "poison.message",
                    MessageCount = (int?)declare.MessageCount,
                    ConsumerCount = (int?)declare.ConsumerCount
                };
            }
            finally
            {
                await channel.CloseAsync(cancellationToken);
                channel.Dispose();
            }
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Failed to get quarantine stats");
            return new QuarantineStatsResponseDto
            {
                Ready = false,
                Queue = QuarantineQueue,
                Error = ex.Message
            };
        }
    }

    public async Task<QueueStatsResponseDto> GetQueueStatsAsync(CancellationToken cancellationToken = default)
    {
        try
        {
            var channel = await _connection.CreateChannelAsync(cancellationToken: cancellationToken);
            try
            {
                var declare = await channel.QueueDeclarePassiveAsync(MainQueue, cancellationToken: cancellationToken);
                return new QueueStatsResponseDto
                {
                    Ready = true,
                    Queue = MainQueue,
                    MessageCount = (int?)declare.MessageCount,
                    ConsumerCount = (int?)declare.ConsumerCount,
                    BacklogOverThreshold = declare.MessageCount > 100u, // Simple threshold
                    WarnThreshold = 100
                };
            }
            finally
            {
                await channel.CloseAsync(cancellationToken);
                channel.Dispose();
            }
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Failed to get queue stats");
            return new QueueStatsResponseDto
            {
                Ready = false,
                Queue = MainQueue,
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
            var channel = await _connection.CreateChannelAsync(cancellationToken: cancellationToken);
            try
            {
                var totalFound = 0;
                var totalReplayed = 0;
                var replayedItems = new List<QuarantineReplayItemDto>();

                // Get messages from quarantine queue
                while (totalFound < maxMessages)
                {
                    var result = await channel.BasicGetAsync(QuarantineQueue, autoAck: false, cancellationToken: cancellationToken);
                    if (result is null)
                        break;

                    totalFound++;

                    try
                    {
                        var body = result.Body.ToArray();
                        var json = System.Text.Encoding.UTF8.GetString(body);

                        // Try to parse the quarantine message
                        using var doc = JsonDocument.Parse(json);
                        var root = doc.RootElement;

                        var taxonomy = root.TryGetProperty("taxonomy", out var taxProp) ? taxProp.GetString() : null;
                        var ageSeconds = root.TryGetProperty("ageSeconds", out var ageProp) ? ageProp.GetInt32() : 0;

                        // Apply filters
                        if (taxonomyPrefixes?.Any() == true && taxonomy != null)
                        {
                            var matchesPrefix = taxonomyPrefixes.Any(p => taxonomy.StartsWith(p, StringComparison.OrdinalIgnoreCase));
                            if (!matchesPrefix)
                            {
                                // NACK and requeue
                                await channel.BasicNackAsync(result.DeliveryTag, multiple: false, requeue: true, cancellationToken: cancellationToken);
                                replayedItems.Add(new QuarantineReplayItemDto
                                {
                                    Taxonomy = taxonomy,
                                    AgeSeconds = ageSeconds,
                                    Replayed = false,
                                    Error = "Did not match taxonomy filter"
                                });
                                continue;
                            }
                        }

                        if (maxAgeSeconds.HasValue && ageSeconds > maxAgeSeconds.Value)
                        {
                            // NACK and requeue
                            await channel.BasicNackAsync(result.DeliveryTag, multiple: false, requeue: true, cancellationToken: cancellationToken);
                            replayedItems.Add(new QuarantineReplayItemDto
                            {
                                Taxonomy = taxonomy,
                                AgeSeconds = ageSeconds,
                                Replayed = false,
                                Error = "Exceeded max age"
                            });
                            continue;
                        }

                        if (!dryRun)
                        {
                            // Get original body from quarantine headers
                            var props = result.BasicProperties;
                            var originalBody = GetOriginalBodyFromQuarantine(props, json);

                            if (originalBody != null)
                            {
                                // Republish to main exchange
                                var publishProps = new BasicProperties
                                {
                                    DeliveryMode = DeliveryModes.Persistent,
                                    ContentType = props?.ContentType ?? "application/json"
                                };

                                var routingKey = DetermineRoutingKey(root);
                                await channel.BasicPublishAsync(
                                    exchange: ExchangeName,
                                    routingKey: routingKey,
                                    mandatory: false,
                                    basicProperties: publishProps,
                                    body: originalBody,
                                    cancellationToken: cancellationToken);
                            }
                        }

                        // ACK the message (it's been processed)
                        await channel.BasicAckAsync(result.DeliveryTag, multiple: false, cancellationToken: cancellationToken);
                        totalReplayed++;

                        replayedItems.Add(new QuarantineReplayItemDto
                        {
                            Taxonomy = taxonomy,
                            AgeSeconds = ageSeconds,
                            Replayed = !dryRun
                        });
                    }
                    catch (Exception ex)
                    {
                        // NACK with requeue on error
                        await channel.BasicNackAsync(result.DeliveryTag, multiple: false, requeue: true, cancellationToken: cancellationToken);
                        replayedItems.Add(new QuarantineReplayItemDto
                        {
                            Replayed = false,
                            Error = ex.Message
                        });
                    }
                }

                return new QuarantineReplayResponseDto
                {
                    Success = true,
                    MessagesReplayed = totalReplayed,
                    MessagesFound = totalFound,
                    DryRun = dryRun,
                    ReplayedItems = replayedItems
                };
            }
            finally
            {
                await channel.CloseAsync(cancellationToken);
                channel.Dispose();
            }
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

    private static byte[]? GetOriginalBodyFromQuarantine(IReadOnlyBasicProperties? props, string currentBody)
    {
        // Try to get original body from headers
        if (props?.Headers?.TryGetValue("x-original-body", out var originalBodyObj) == true)
        {
            if (originalBodyObj is byte[] originalBodyBytes)
                return originalBodyBytes;
        }

        // Fallback: try to parse the current body as a quarantine message
        try
        {
            using var doc = JsonDocument.Parse(currentBody);
            var root = doc.RootElement;

            if (root.TryGetProperty("originalBodyBase64", out var base64Prop))
            {
                var base64 = base64Prop.GetString();
                if (!string.IsNullOrEmpty(base64))
                    return Convert.FromBase64String(base64);
            }

            if (root.TryGetProperty("originalBody", out var bodyProp))
            {
                var body = bodyProp.GetString();
                if (!string.IsNullOrEmpty(body))
                    return System.Text.Encoding.UTF8.GetBytes(body);
            }
        }
        catch
        {
            // Ignore parsing errors
        }

        return null;
    }

    private static string DetermineRoutingKey(JsonElement message)
    {
        // Try to determine the original routing key from the message
        if (message.TryGetProperty("routingKey", out var routingKeyProp))
        {
            var routingKey = routingKeyProp.GetString();
            if (!string.IsNullOrEmpty(routingKey))
                return routingKey;
        }

        // Default fallback
        return MessagingConstants.RoutingKeys.AiAnalysisRequested;
    }
}
