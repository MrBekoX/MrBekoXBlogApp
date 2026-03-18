using BlogApp.BuildingBlocks.Messaging.Events;

namespace BlogApp.Server.Application.Common.Events;

public record ChatRequestedEvent : IntegrationEvent
{
    public override string EventType => "chat.message.requested";
    public ChatRequestPayload Payload { get; init; } = new();
}

public record ChatRequestPayload
{
    public string SessionId { get; init; } = string.Empty;
    public Guid PostId { get; init; }
    public string ArticleTitle { get; init; } = string.Empty;
    public string ArticleContent { get; init; } = string.Empty;
    public string UserMessage { get; init; } = string.Empty;
    public List<ChatHistoryItem> ConversationHistory { get; init; } = [];
    public string Language { get; init; } = "tr";
    public bool EnableWebSearch { get; init; }
    public ChatAuthorizationContext AuthContext { get; init; } = new();
}

public record ChatAuthorizationContext
{
    public string SubjectType { get; init; } = "anonymous";
    public string? SubjectId { get; init; }
    public List<string> Roles { get; init; } = [];
    public string? Fingerprint { get; init; }
}

public record ChatHistoryItem
{
    public string Role { get; init; } = string.Empty;
    public string Content { get; init; } = string.Empty;
}

public record ChatResponseEvent : IntegrationEvent
{
    public override string EventType => "chat.message.completed";
    public ChatResponsePayload Payload { get; init; } = new();
}

public record ChatResponsePayload
{
    public string SessionId { get; init; } = string.Empty;
    public string Response { get; init; } = string.Empty;
    public bool IsWebSearchResult { get; init; }
    public List<WebSearchSource>? Sources { get; init; }
}

public record WebSearchSource
{
    public string Title { get; init; } = string.Empty;
    public string Url { get; init; } = string.Empty;
    public string Snippet { get; init; } = string.Empty;
}
