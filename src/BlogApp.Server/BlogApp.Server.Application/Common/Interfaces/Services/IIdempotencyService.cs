using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Domain.Entities;

namespace BlogApp.Server.Application.Common.Interfaces.Services;

public interface IIdempotencyService
{
    Task<IdempotencyStartResult> BeginRequestAsync(IdempotencyStartRequest request, CancellationToken cancellationToken = default);
    Task<IdempotencyRecord?> GetRequestByOperationAsync(string endpointName, string operationId, CancellationToken cancellationToken = default);
    Task<IdempotencyRecord?> GetRequestByCorrelationIdAsync(string correlationId, CancellationToken cancellationToken = default);
    Task MarkCompletedByCorrelationAsync(
        string correlationId,
        int finalHttpStatus,
        object finalResponse,
        CancellationToken cancellationToken = default,
        IReadOnlyDictionary<string, string[]>? finalResponseHeaders = null);
    Task MarkFailedByCorrelationAsync(string correlationId, string errorCode, string errorMessage, CancellationToken cancellationToken = default);
    Task<ConsumerClaimResult> ClaimConsumerAsync(string consumerName, string operationId, Guid? messageId, string? correlationId, CancellationToken cancellationToken = default);
    Task MarkConsumerCompletedAsync(Guid inboxId, CancellationToken cancellationToken = default);
    Task MarkConsumerFailedAsync(Guid inboxId, string error, CancellationToken cancellationToken = default);
}
