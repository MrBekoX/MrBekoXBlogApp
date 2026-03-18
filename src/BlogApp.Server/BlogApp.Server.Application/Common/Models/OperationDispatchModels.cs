using BlogApp.BuildingBlocks.Messaging.Abstractions;

namespace BlogApp.Server.Application.Common.Models;

public enum AiGenerationExecutionState
{
    Completed = 0,
    Processing = 1,
    Conflict = 2,
    Failed = 3
}

public record AiGenerationExecutionRequest<TEvent>(
    string EndpointName,
    string OperationId,
    object RequestPayload,
    Guid? UserId,
    string? ResourceId,
    Func<string, string, string?, TEvent> BuildEvent,
    string RoutingKey,
    TimeSpan Timeout)
    where TEvent : IIntegrationEvent;

public record AiGenerationExecutionResult<TResult>(
    AiGenerationExecutionState State,
    string OperationId,
    string CorrelationId,
    TResult? Result,
    string? ErrorCode = null,
    string? ErrorMessage = null);

public enum AsyncOperationDispatchState
{
    Started = 0,
    Processing = 1,
    Completed = 2,
    Conflict = 3,
    Failed = 4
}

public record AsyncOperationDispatchRequest<TEvent>(
    string EndpointName,
    string OperationId,
    object RequestPayload,
    Guid? UserId,
    string? SessionId,
    string? ResourceId,
    Func<string, string, string?, TEvent> BuildEvent,
    string RoutingKey,
    int AcceptedStatusCode,
    Func<string, string, object> BuildAcceptedResponse)
    where TEvent : IIntegrationEvent;

public record AsyncOperationDispatchResult(
    AsyncOperationDispatchState State,
    string OperationId,
    string CorrelationId,
    StoredHttpResponse Response,
    string? ErrorCode = null,
    string? ErrorMessage = null);
