using BlogApp.BuildingBlocks.Messaging.Abstractions;
using BlogApp.Server.Api.Hubs;
using BlogApp.Server.Application.Common.Events;
using BlogApp.Server.Application.Common.Interfaces.Services;
using BlogApp.Server.Application.Common.Models;
using Microsoft.AspNetCore.SignalR;

namespace BlogApp.Server.Api.Messaging;

public class ChatResponseHandler : IEventHandler<ChatResponseEvent>
{
    private const string ConsumerName = "backend.chat-response-handler";

    private readonly IHubContext<ChatEventsHub> _hubContext;
    private readonly IIdempotencyService _idempotencyService;
    private readonly ILogger<ChatResponseHandler> _logger;

    public ChatResponseHandler(
        IHubContext<ChatEventsHub> hubContext,
        IIdempotencyService idempotencyService,
        ILogger<ChatResponseHandler> logger)
    {
        _hubContext = hubContext;
        _idempotencyService = idempotencyService;
        _logger = logger;
    }

    public async Task HandleAsync(ChatResponseEvent @event, CancellationToken cancellationToken = default)
    {
        var operationId = @event.OperationId ?? @event.MessageId.ToString();
        var claim = await _idempotencyService.ClaimConsumerAsync(
            ConsumerName,
            operationId,
            @event.MessageId,
            @event.CorrelationId,
            cancellationToken);

        if (claim.State is ConsumerClaimState.DuplicateCompleted or ConsumerClaimState.DuplicateProcessing)
        {
            _logger.LogInformation(
                "Skipping duplicate chat response for operation {OperationId} ({State})",
                operationId,
                claim.State);
            return;
        }

        var sessionId = @event.Payload.SessionId;
        var correlationId = @event.CorrelationId;

        try
        {
            var responseData = new
            {
                SessionId = sessionId,
                OperationId = operationId,
                CorrelationId = correlationId,
                Response = @event.Payload.Response,
                IsWebSearchResult = @event.Payload.IsWebSearchResult,
                Sources = @event.Payload.Sources?.Select(s => new
                {
                    s.Title,
                    s.Url,
                    s.Snippet
                }),
                Timestamp = DateTime.UtcNow
            };

            await _hubContext.Clients.Group($"chat_{sessionId}").SendAsync(
                "ChatMessageReceived",
                responseData,
                cancellationToken);

            if (!string.IsNullOrWhiteSpace(correlationId))
            {
                await _idempotencyService.MarkCompletedByCorrelationAsync(correlationId, StatusCodes.Status200OK, responseData, cancellationToken);
            }

            await _idempotencyService.MarkConsumerCompletedAsync(claim.Record.Id, cancellationToken);
        }
        catch (Exception ex)
        {
            await _idempotencyService.MarkConsumerFailedAsync(claim.Record.Id, ex.Message, cancellationToken);
            _logger.LogError(ex, "Error broadcasting chat response for session {SessionId}", sessionId);
            throw;
        }
    }
}

public class ChatChunkHandler : IEventHandler<ChatChunkEvent>
{
    private const string ConsumerName = "backend.chat-chunk-handler";

    private readonly IHubContext<ChatEventsHub> _hubContext;
    private readonly IIdempotencyService _idempotencyService;
    private readonly ILogger<ChatChunkHandler> _logger;

    public ChatChunkHandler(
        IHubContext<ChatEventsHub> hubContext,
        IIdempotencyService idempotencyService,
        ILogger<ChatChunkHandler> logger)
    {
        _hubContext = hubContext;
        _idempotencyService = idempotencyService;
        _logger = logger;
    }

    public async Task HandleAsync(ChatChunkEvent @event, CancellationToken cancellationToken = default)
    {
        var payload = @event.Payload;
        var sessionId = payload.SessionId;
        var operationBase = @event.OperationId ?? @event.MessageId.ToString();
        var chunkOperationId = $"{operationBase}:chunk:{payload.Sequence}";
        var claim = await _idempotencyService.ClaimConsumerAsync(
            ConsumerName,
            chunkOperationId,
            @event.MessageId,
            @event.CorrelationId,
            cancellationToken);

        if (claim.State is ConsumerClaimState.DuplicateCompleted or ConsumerClaimState.DuplicateProcessing)
        {
            _logger.LogInformation(
                "Skipping duplicate chat chunk for operation {ChunkOperationId} ({State})",
                chunkOperationId,
                claim.State);
            return;
        }

        try
        {
            await _hubContext.Clients.Group($"chat_{sessionId}").SendAsync(
                "ChatChunkReceived",
                new
                {
                    SessionId = sessionId,
                    OperationId = @event.OperationId,
                    Chunk = payload.Chunk,
                    Sequence = payload.Sequence,
                    IsFinal = payload.IsFinal,
                    Timestamp = DateTime.UtcNow
                },
                cancellationToken);

            if (payload.IsFinal)
            {
                await _hubContext.Clients.Group($"chat_{sessionId}").SendAsync(
                    "ChatMessageCompleted",
                    new { SessionId = sessionId, OperationId = @event.OperationId, Timestamp = DateTime.UtcNow },
                    cancellationToken);
            }

            await _idempotencyService.MarkConsumerCompletedAsync(claim.Record.Id, cancellationToken);
        }
        catch (Exception ex)
        {
            await _idempotencyService.MarkConsumerFailedAsync(claim.Record.Id, ex.Message, cancellationToken);
            _logger.LogError(ex, "Error broadcasting chat chunk for session {SessionId}", sessionId);
            throw;
        }
    }
}

public record ChatChunkEvent : BlogApp.BuildingBlocks.Messaging.Events.IntegrationEvent
{
    public override string EventType => "chat.chunk.completed";
    public ChatChunkPayload Payload { get; init; } = null!;
}

public record ChatChunkPayload
{
    public string SessionId { get; init; } = string.Empty;
    public string Chunk { get; init; } = string.Empty;
    public int Sequence { get; init; }
    public bool IsFinal { get; init; }
}
