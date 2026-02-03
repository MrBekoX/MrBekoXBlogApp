using BlogApp.BuildingBlocks.Messaging.Events;

namespace BlogApp.Server.Application.Common.Events;

/// <summary>
/// Event published by Backend to request a chat response from AI Agent.
/// </summary>
public record ChatRequestedEvent : IntegrationEvent
{
    public override string EventType => "chat.message.requested";

    /// <summary>
    /// Chat request payload
    /// </summary>
    public ChatRequestPayload Payload { get; init; } = new();
}

/// <summary>
/// Payload for chat request
/// </summary>
public record ChatRequestPayload
{
    /// <summary>
    /// Session ID for the chat conversation
    /// </summary>
    public string SessionId { get; init; } = string.Empty;

    /// <summary>
    /// Post ID that the chat is about
    /// </summary>
    public Guid PostId { get; init; }

    /// <summary>
    /// Article title for context
    /// </summary>
    public string ArticleTitle { get; init; } = string.Empty;

    /// <summary>
    /// Article content for RAG (optional, used for indexing)
    /// </summary>
    public string ArticleContent { get; init; } = string.Empty;

    /// <summary>
    /// User's message
    /// </summary>
    public string UserMessage { get; init; } = string.Empty;

    /// <summary>
    /// Previous conversation messages
    /// </summary>
    public List<ChatHistoryItem> ConversationHistory { get; init; } = [];

    /// <summary>
    /// Response language (tr, en)
    /// </summary>
    public string Language { get; init; } = "tr";

    /// <summary>
    /// Enable web search for additional information
    /// </summary>
    public bool EnableWebSearch { get; init; }
}

/// <summary>
/// A single message in the conversation history
/// </summary>
public record ChatHistoryItem
{
    /// <summary>
    /// Role: "user" or "assistant"
    /// </summary>
    public string Role { get; init; } = string.Empty;

    /// <summary>
    /// Message content
    /// </summary>
    public string Content { get; init; } = string.Empty;
}

/// <summary>
/// Event published by AI Agent when chat response is ready.
/// Backend consumes this and broadcasts via SignalR.
/// </summary>
public record ChatResponseEvent : IntegrationEvent
{
    public override string EventType => "chat.message.completed";

    /// <summary>
    /// Chat response payload
    /// </summary>
    public ChatResponsePayload Payload { get; init; } = new();
}

/// <summary>
/// Payload for chat response
/// </summary>
public record ChatResponsePayload
{
    /// <summary>
    /// Session ID for the chat conversation
    /// </summary>
    public string SessionId { get; init; } = string.Empty;

    /// <summary>
    /// AI-generated response
    /// </summary>
    public string Response { get; init; } = string.Empty;

    /// <summary>
    /// Whether the response includes web search results
    /// </summary>
    public bool IsWebSearchResult { get; init; }

    /// <summary>
    /// Web search sources (if web search was used)
    /// </summary>
    public List<WebSearchSource>? Sources { get; init; }
}

/// <summary>
/// A web search source
/// </summary>
public record WebSearchSource
{
    /// <summary>
    /// Source title
    /// </summary>
    public string Title { get; init; } = string.Empty;

    /// <summary>
    /// Source URL
    /// </summary>
    public string Url { get; init; } = string.Empty;

    /// <summary>
    /// Source snippet/description
    /// </summary>
    public string Snippet { get; init; } = string.Empty;
}
