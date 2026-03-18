using BlogApp.Server.Domain.Entities;

namespace BlogApp.Server.Application.Common.Models;

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

public enum ConsumerClaimState
{
    Claimed = 0,
    DuplicateProcessing = 1,
    DuplicateCompleted = 2,
    Failed = 3
}

public record ConsumerClaimResult(
    ConsumerClaimState State,
    ConsumerInboxMessage Record);

public record StoredHttpResponse(
    int StatusCode,
    string Json,
    IReadOnlyDictionary<string, string[]>? Headers = null,
    string ContentType = "application/json; charset=utf-8");
