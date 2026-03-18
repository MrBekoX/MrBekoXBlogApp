using BlogApp.BuildingBlocks.Messaging.Abstractions;

namespace BlogApp.BuildingBlocks.Messaging.Events.Ai;

/// <summary>
/// Event triggered when AI Agent streams a chat chunk (chunked streaming)
/// </summary>
public record ChatChunkCompletedEvent : IntegrationEvent
{
    public override string EventType => "chat.chunk.completed";
    public ChatChunkPayload Payload { get; init; } = null!;
}

/// <summary>
/// Payload for chat chunk event
/// </summary>
public record ChatChunkPayload
{
    public string SessionId { get; init; } = string.Empty;
    public string Chunk { get; init; } = string.Empty;
    public int Sequence { get; init; }
    public bool IsFinal { get; init; }
}
