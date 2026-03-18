using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.DependencyInjection;
using BlogApp.Server.Application.Common.Models;
using System.Text;
using System.Text.Json;
using BlogApp.BuildingBlocks.Messaging;
using BlogApp.BuildingBlocks.Messaging.Options;
using BlogApp.BuildingBlocks.Messaging.RabbitMQ;
using BlogApp.Server.Application.Common.Interfaces.Services;
using BlogApp.Server.Domain.Entities;
using BlogApp.Server.Api.Hubs;
using Microsoft.Extensions.Options;
using RabbitMQ.Client;
using RabbitMQ.Client.Events;
using Microsoft.AspNetCore.SignalR;

namespace BlogApp.Server.Api.Messaging;

/// <summary>
/// Background service that consumes AI generation completion events from RabbitMQ,
/// stores final idempotent responses, and broadcasts authoring completions to SignalR.
/// </summary>
public class AiGenerationResponseConsumer(
    RabbitMqConnection connection,
    IOptions<RabbitMqSettings> settings,
    IAiGenerationCorrelationService correlationService,
    IServiceScopeFactory scopeFactory,
    IHubContext<AuthoringEventsHub> hubContext,
    ILogger<AiGenerationResponseConsumer> logger) : BackgroundService
{
    private static readonly string[] CompletedRoutingKeys =
    [
        MessagingConstants.RoutingKeys.AiTitleGenerationCompleted,
        MessagingConstants.RoutingKeys.AiExcerptGenerationCompleted,
        MessagingConstants.RoutingKeys.AiTagsGenerationCompleted,
        MessagingConstants.RoutingKeys.AiSeoGenerationCompleted,
        MessagingConstants.RoutingKeys.AiContentImprovementCompleted,
        MessagingConstants.RoutingKeys.AiSummarizeCompleted,
        MessagingConstants.RoutingKeys.AiKeywordsCompleted,
        MessagingConstants.RoutingKeys.AiSentimentCompleted,
        MessagingConstants.RoutingKeys.AiReadingTimeCompleted,
        MessagingConstants.RoutingKeys.AiGeoOptimizeCompleted,
        MessagingConstants.RoutingKeys.AiCollectSourcesCompleted,
    ];

    private const string ConsumerName = "backend.ai-generation-response-consumer";

    private IChannel? _channel;
    private string? _consumerTag;

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        if (!settings.Value.Enabled)
        {
            logger.LogInformation("RabbitMQ disabled, AI generation response consumer will not start");
            return;
        }

        try
        {
            _channel = await connection.CreateChannelAsync(publisherConfirms: false, cancellationToken: stoppingToken);
            await _channel.BasicQosAsync(prefetchSize: 0, prefetchCount: 5, global: false, cancellationToken: stoppingToken);

            await _channel.ExchangeDeclareAsync(
                exchange: MessagingConstants.ExchangeName,
                type: ExchangeType.Direct,
                durable: true,
                autoDelete: false,
                cancellationToken: stoppingToken);

            await _channel.QueueDeclareAsync(
                queue: MessagingConstants.QueueNames.AiGenerationCompleted,
                durable: true,
                exclusive: false,
                autoDelete: false,
                arguments: new Dictionary<string, object?>
                {
                    ["x-dead-letter-exchange"] = MessagingConstants.DeadLetterExchange,
                    ["x-queue-type"] = "quorum"
                },
                cancellationToken: stoppingToken);

            foreach (var routingKey in CompletedRoutingKeys)
            {
                await _channel.QueueBindAsync(
                    queue: MessagingConstants.QueueNames.AiGenerationCompleted,
                    exchange: MessagingConstants.ExchangeName,
                    routingKey: routingKey,
                    cancellationToken: stoppingToken);
            }

            var consumer = new AsyncEventingBasicConsumer(_channel);
            consumer.ReceivedAsync += async (_, args) => await HandleMessageAsync(args);

            _consumerTag = await _channel.BasicConsumeAsync(
                queue: MessagingConstants.QueueNames.AiGenerationCompleted,
                autoAck: false,
                consumer: consumer,
                cancellationToken: stoppingToken);

            await Task.Delay(Timeout.Infinite, stoppingToken);
        }
        catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested)
        {
            logger.LogInformation("AI generation response consumer stopping");
        }
    }

    private async Task HandleMessageAsync(BasicDeliverEventArgs args)
    {
        var deliveryTag = args.DeliveryTag;
        var messageId = args.BasicProperties?.MessageId ?? "unknown";
        Guid? parsedMessageId = Guid.TryParse(messageId, out var messageGuid) ? messageGuid : null;
        Guid? inboxId = null;

        try
        {
            var body = Encoding.UTF8.GetString(args.Body.ToArray());
            using var doc = JsonDocument.Parse(body);
            var root = doc.RootElement;

            var correlationId = root.TryGetProperty("correlationId", out var cid) ? cid.GetString() : null;
            var eventType = root.TryGetProperty("eventType", out var et) ? et.GetString() : null;
            var operationId = root.TryGetProperty("operationId", out var op) && op.ValueKind == JsonValueKind.String
                ? op.GetString()
                : null;
            operationId ??= correlationId ?? messageId;

            if (string.IsNullOrEmpty(correlationId) || string.IsNullOrEmpty(eventType))
            {
                await NackAsync(deliveryTag, requeue: false);
                return;
            }

            if (!root.TryGetProperty("payload", out var payload))
            {
                await NackAsync(deliveryTag, requeue: false);
                return;
            }

            await using var scope = scopeFactory.CreateAsyncScope();
            var idempotencyService = scope.ServiceProvider.GetRequiredService<IIdempotencyService>();
            var claim = await idempotencyService.ClaimConsumerAsync(
                ConsumerName,
                operationId,
                parsedMessageId,
                correlationId,
                CancellationToken.None);

            inboxId = claim.Record.Id;
            if (claim.State is ConsumerClaimState.DuplicateCompleted or ConsumerClaimState.DuplicateProcessing)
            {
                await AckAsync(deliveryTag);
                return;
            }

            object? result = eventType switch
            {
                "ai.title.generation.completed" => GetString(payload, "title"),
                "ai.excerpt.generation.completed" => GetString(payload, "excerpt"),
                "ai.tags.generation.completed" => GetStringArray(payload, "tags"),
                "ai.seo.generation.completed" => GetString(payload, "description"),
                "ai.content.improvement.completed" => GetString(payload, "content") ?? GetString(payload, "improvedContent"),
                "ai.summarize.completed" => GetString(payload, "summary"),
                "ai.keywords.completed" => GetStringArray(payload, "keywords"),
                "ai.sentiment.completed" => ExtractSentiment(payload),
                "ai.reading-time.completed" => ExtractReadingTime(payload),
                "ai.geo-optimize.completed" => ExtractGeoOptimization(payload),
                "ai.collect-sources.completed" => ExtractSources(payload),
                _ => null
            };

            if (result is null)
            {
                await idempotencyService.MarkConsumerFailedAsync(claim.Record.Id, $"Unsupported event type: {eventType}", CancellationToken.None);
                await NackAsync(deliveryTag, requeue: false);
                return;
            }

            var requestRecord = await idempotencyService.GetRequestByCorrelationIdAsync(correlationId, CancellationToken.None);
            await PublishCompletionEventAsync(eventType, operationId, correlationId, requestRecord, result);

            correlationService.TryComplete(correlationId, result);
            await idempotencyService.MarkCompletedByCorrelationAsync(correlationId, StatusCodes.Status200OK, result, CancellationToken.None);
            await idempotencyService.MarkConsumerCompletedAsync(claim.Record.Id, CancellationToken.None);

            await AckAsync(deliveryTag);
        }
        catch (JsonException ex)
        {
            logger.LogError(ex, "Failed to parse AI generation response {MessageId}", messageId);
            if (inboxId.HasValue)
            {
                await MarkInboxFailedAsync(inboxId.Value, ex.Message);
            }
            await NackAsync(deliveryTag, requeue: false);
        }
        catch (Exception ex)
        {
            logger.LogError(ex, "Error handling AI generation response {MessageId}", messageId);
            if (inboxId.HasValue)
            {
                await MarkInboxFailedAsync(inboxId.Value, ex.Message);
            }

            const int maxRetries = 3;
            var deliveryCount = GetDeliveryCount(args);
            await NackAsync(deliveryTag, requeue: deliveryCount < maxRetries);
        }
    }

    private async Task MarkInboxFailedAsync(Guid inboxId, string error)
    {
        await using var scope = scopeFactory.CreateAsyncScope();
        var idempotencyService = scope.ServiceProvider.GetRequiredService<IIdempotencyService>();
        await idempotencyService.MarkConsumerFailedAsync(inboxId, error, CancellationToken.None);
    }

    private static int GetDeliveryCount(BasicDeliverEventArgs args)
    {
        if (args.BasicProperties?.Headers?.TryGetValue("x-delivery-count", out var count) == true)
        {
            return count switch
            {
                int intCount => intCount,
                long longCount => (int)longCount,
                _ => 1
            };
        }
        return 1;
    }

    private static string? GetString(JsonElement payload, string property)
    {
        return payload.TryGetProperty(property, out var prop) ? prop.GetString() : null;
    }

    private static string[]? GetStringArray(JsonElement payload, string property)
    {
        if (!payload.TryGetProperty(property, out var prop) || prop.ValueKind != JsonValueKind.Array)
            return null;

        return prop.EnumerateArray()
            .Select(e => e.GetString() ?? string.Empty)
            .ToArray();
    }

    private static object? ExtractSentiment(JsonElement payload)
    {
        if (!payload.TryGetProperty("sentiment", out var sentimentProp))
            return null;

        return new
        {
            Sentiment = sentimentProp.GetString() ?? string.Empty,
            Confidence = payload.TryGetProperty("confidence", out var confProp) ? confProp.GetDouble() : 0.0
        };
    }

    private static object? ExtractReadingTime(JsonElement payload)
    {
        if (!payload.TryGetProperty("readingTimeMinutes", out var minutesProp))
            return null;

        return new
        {
            ReadingTimeMinutes = minutesProp.GetInt32(),
            WordCount = payload.TryGetProperty("wordCount", out var wordCountProp) ? wordCountProp.GetInt32() : 0
        };
    }

    private static object? ExtractGeoOptimization(JsonElement payload)
    {
        if (!payload.TryGetProperty("geoOptimization", out var geoProp) || geoProp.ValueKind == JsonValueKind.Null)
            return null;

        return new
        {
            TargetRegion = geoProp.TryGetProperty("targetRegion", out var regionProp) ? regionProp.GetString() ?? string.Empty : string.Empty,
            LocalizedTitle = geoProp.TryGetProperty("localizedTitle", out var titleProp) ? titleProp.GetString() ?? string.Empty : string.Empty,
            LocalizedSummary = geoProp.TryGetProperty("localizedSummary", out var summaryProp) ? summaryProp.GetString() ?? string.Empty : string.Empty,
            LocalizedKeywords = geoProp.TryGetProperty("localizedKeywords", out var keywordsProp) && keywordsProp.ValueKind == JsonValueKind.Array
                ? keywordsProp.EnumerateArray().Select(e => e.GetString() ?? string.Empty).ToArray()
                : Array.Empty<string>(),
            CulturalNotes = geoProp.TryGetProperty("culturalNotes", out var notesProp) ? notesProp.GetString() ?? string.Empty : string.Empty
        };
    }

    private static object? ExtractSources(JsonElement payload)
    {
        if (!payload.TryGetProperty("sources", out var sourcesProp) || sourcesProp.ValueKind != JsonValueKind.Array)
            return null;

        return sourcesProp.EnumerateArray()
            .Select(s => new
            {
                Title = s.TryGetProperty("title", out var titleProp) ? titleProp.GetString() ?? string.Empty : string.Empty,
                Url = s.TryGetProperty("url", out var urlProp) ? urlProp.GetString() ?? string.Empty : string.Empty,
                Snippet = s.TryGetProperty("snippet", out var snippetProp) ? snippetProp.GetString() ?? string.Empty : string.Empty
            })
            .ToArray();
    }

    private async Task PublishCompletionEventAsync(
        string eventType,
        string operationId,
        string correlationId,
        IdempotencyRecord? requestRecord,
        object result)
    {
        if (requestRecord?.UserId is not Guid userId)
        {
            return;
        }

        var responseData = new
        {
            OperationId = operationId,
            CorrelationId = correlationId,
            OperationType = eventType,
            ResourceId = requestRecord.ResourceId,
            Result = result,
            Timestamp = DateTime.UtcNow
        };

        await hubContext.Clients.Group($"user_{userId}").SendAsync(
            "AiOperationCompleted",
            responseData,
            CancellationToken.None);
    }

    private async Task AckAsync(ulong deliveryTag)
    {
        if (_channel is not null)
        {
            await _channel.BasicAckAsync(deliveryTag, multiple: false);
        }
    }

    private async Task NackAsync(ulong deliveryTag, bool requeue)
    {
        if (_channel is not null)
        {
            await _channel.BasicNackAsync(deliveryTag, multiple: false, requeue: requeue);
        }
    }

    public override async Task StopAsync(CancellationToken cancellationToken)
    {
        if (_channel is not null)
        {
            if (_consumerTag is not null)
            {
                try
                {
                    await _channel.BasicCancelAsync(_consumerTag, cancellationToken: cancellationToken);
                }
                catch (Exception ex)
                {
                    logger.LogWarning(ex, "Error cancelling AI generation response consumer");
                }
            }

            await _channel.CloseAsync(cancellationToken);
            _channel.Dispose();
        }

        await base.StopAsync(cancellationToken);
    }
}