using BlogApp.BuildingBlocks.Messaging;
using BlogApp.BuildingBlocks.Messaging.Abstractions;
using BlogApp.Server.Application.Common.Events;
using BlogApp.Server.Application.Common.Interfaces.Persistence;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.RateLimiting;

namespace BlogApp.Server.Api.Endpoints;

public static class ChatEndpoints
{
    public static IEndpointRouteBuilder RegisterChatEndpoints(this IEndpointRouteBuilder app)
    {
        var versionedGroup = app.NewVersionedApi("Chat");
        var group = versionedGroup.MapGroup("/api/v{version:apiVersion}/chat")
            .HasApiVersion(1.0)
            .WithTags("Chat")
            .RequireAuthorization();

        // POST /api/v1/chat/message
        group.MapPost("/message", async (
            ChatMessageRequest request,
            IEventBus eventBus,
            IUnitOfWork unitOfWork,
            HttpContext httpContext,
            CancellationToken cancellationToken) =>
        {
            // Validate post exists
            var post = await unitOfWork.PostsRead.GetByIdAsync(request.PostId, cancellationToken);
            if (post is null)
            {
                return Results.NotFound(new { message = "Post not found" });
            }

            // Generate session ID if not provided
            var sessionId = string.IsNullOrEmpty(request.SessionId)
                ? Guid.NewGuid().ToString()
                : request.SessionId;

            // Create correlation ID for tracking
            var correlationId = Guid.NewGuid().ToString();

            // Build conversation history
            var history = request.ConversationHistory?
                .Select(h => new ChatHistoryItem
                {
                    Role = h.Role,
                    Content = h.Content
                })
                .ToList() ?? [];

            // Publish chat request event
            var chatEvent = new ChatRequestedEvent
            {
                CorrelationId = correlationId,
                Payload = new ChatRequestPayload
                {
                    SessionId = sessionId,
                    PostId = request.PostId,
                    ArticleTitle = post.Title,
                    ArticleContent = post.Content,
                    UserMessage = request.Message,
                    ConversationHistory = history,
                    Language = request.Language ?? "tr",
                    EnableWebSearch = request.EnableWebSearch
                }
            };

            await eventBus.PublishAsync(
                chatEvent,
                MessagingConstants.RoutingKeys.ChatMessageRequested,
                cancellationToken);

            return Results.Accepted(value: new
            {
                correlationId,
                sessionId,
                message = "Chat request accepted"
            });
        })
        .WithName("SendChatMessage")
        .Produces(StatusCodes.Status202Accepted)
        .ProducesProblem(StatusCodes.Status404NotFound)
        .ProducesProblem(StatusCodes.Status429TooManyRequests);

        return app;
    }
}

// Request DTOs
public record ChatMessageRequest
{
    /// <summary>
    /// Post ID to chat about
    /// </summary>
    public Guid PostId { get; init; }

    /// <summary>
    /// User's message
    /// </summary>
    public string Message { get; init; } = string.Empty;

    /// <summary>
    /// Session ID for continuing conversation (optional)
    /// </summary>
    public string? SessionId { get; init; }

    /// <summary>
    /// Previous conversation messages (optional)
    /// </summary>
    public List<ChatHistoryItemRequest>? ConversationHistory { get; init; }

    /// <summary>
    /// Response language (default: tr)
    /// </summary>
    public string? Language { get; init; }

    /// <summary>
    /// Enable web search for additional context
    /// </summary>
    public bool EnableWebSearch { get; init; }
}

public record ChatHistoryItemRequest
{
    public string Role { get; init; } = string.Empty;
    public string Content { get; init; } = string.Empty;
}
