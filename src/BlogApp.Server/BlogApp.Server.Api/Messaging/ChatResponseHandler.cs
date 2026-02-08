using BlogApp.BuildingBlocks.Messaging.Abstractions;
using BlogApp.Server.Api.Hubs;
using BlogApp.Server.Application.Common.Events;
using Microsoft.AspNetCore.SignalR;

namespace BlogApp.Server.Api.Messaging;

/// <summary>
/// Handles chat response events from RabbitMQ.
/// Broadcasts the response to connected clients via SignalR.
/// </summary>
public class ChatResponseHandler : IEventHandler<ChatResponseEvent>
{
    private readonly IHubContext<CacheInvalidationHub> _hubContext;
    private readonly ILogger<ChatResponseHandler> _logger;

    public ChatResponseHandler(
        IHubContext<CacheInvalidationHub> hubContext,
        ILogger<ChatResponseHandler> logger)
    {
        _hubContext = hubContext;
        _logger = logger;
    }

    public async Task HandleAsync(ChatResponseEvent @event, CancellationToken cancellationToken = default)
    {
        var sessionId = @event.Payload.SessionId;
        var correlationId = @event.CorrelationId;

        _logger.LogInformation(
            "Processing chat response for session {SessionId} (CorrelationId: {CorrelationId})",
            sessionId,
            correlationId);

        try
        {
            // Prepare the response data for SignalR
            var responseData = new
            {
                SessionId = sessionId,
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

            // Send only to clients subscribed to this chat session
            await _hubContext.Clients.Group($"chat_{sessionId}").SendAsync(
                "ChatMessageReceived",
                responseData,
                cancellationToken);
        }
        catch (Exception ex)
        {
            _logger.LogError(
                ex,
                "Error broadcasting chat response for session {SessionId}",
                sessionId);
            throw;
        }
    }
}
