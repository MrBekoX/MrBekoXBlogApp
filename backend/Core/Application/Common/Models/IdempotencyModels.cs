using BlogApp.Core.Domain.Entities;

namespace BlogApp.Core.Application.Common.Models;

public enum IdempotencyStartState
{
    Started = 0,
    Processing = 1,
    Completed = 2,
    Failed = 3,
    Conflict = 4
}

public record IdempotencyStartRequest(
    string EndpointName,
    string OperationId,
    string RequestHash,
    string CorrelationId,
    string? CausationId,
    int AcceptedHttpStatus,
    string? AcceptedResponseJson,
    Guid? UserId,
    string? SessionId,
    string? ResourceId);

public record IdempotencyStartResult(
    IdempotencyStartState State,
    IdempotencyRecord Record);

public record StoredHttpResponse(
    int StatusCode,
    string Json,
    IReadOnlyDictionary<string, string[]>? Headers = null,
    string ContentType = "application/json; charset=utf-8");
