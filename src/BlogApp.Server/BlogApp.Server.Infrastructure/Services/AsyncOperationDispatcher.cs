using System.Text.Json;
using System.Text.Json.Serialization;
using BlogApp.BuildingBlocks.Messaging.Abstractions;
using BlogApp.Server.Application.Common.Constants;
using BlogApp.Server.Application.Common.Interfaces.Services;
using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.Common.Utilities;
using BlogApp.Server.Infrastructure.Persistence;
using Microsoft.AspNetCore.Http;
using Microsoft.EntityFrameworkCore;

namespace BlogApp.Server.Infrastructure.Services;

public class AsyncOperationDispatcher(
    AppDbContext context,
    IIdempotencyService idempotencyService,
    IOutboxService outboxService,
    ICurrentUserService currentUserService) : IAsyncOperationDispatcher
{
    private static readonly JsonSerializerOptions SerializerOptions = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
        WriteIndented = false
    };

    public async Task<AsyncOperationDispatchResult> DispatchAsync<TEvent>(
        AsyncOperationDispatchRequest<TEvent> request,
        CancellationToken cancellationToken = default)
        where TEvent : IIntegrationEvent
    {
        if (!outboxService.IsEnabled)
        {
            return new AsyncOperationDispatchResult(
                AsyncOperationDispatchState.Failed,
                request.OperationId,
                string.Empty,
                new StoredHttpResponse(
                    StatusCodes.Status503ServiceUnavailable,
                    string.Empty),
                AsyncOperationErrorCodes.AsyncDispatchUnavailable,
                "Asynchronous processing is temporarily unavailable.");
        }

        var correlationId = Guid.NewGuid().ToString();
        var causationId = currentUserService.CorrelationId;
        var requestHash = IdempotencyRequestHasher.Compute(request.RequestPayload);
        var acceptedPayload = request.BuildAcceptedResponse(request.OperationId, correlationId);
        var acceptedJson = JsonSerializer.Serialize(acceptedPayload, SerializerOptions);

        var strategy = context.Database.CreateExecutionStrategy();
        var transactionResult = await strategy.ExecuteAsync(async () =>
        {
            await using var transaction = await context.Database.BeginTransactionAsync(cancellationToken);
            var startResult = await idempotencyService.BeginRequestAsync(
                new IdempotencyStartRequest(
                    request.EndpointName,
                    request.OperationId,
                    requestHash,
                    correlationId,
                    causationId,
                    request.AcceptedStatusCode,
                    acceptedJson,
                    request.UserId,
                    request.SessionId,
                    request.ResourceId),
                cancellationToken);

            switch (startResult.State)
            {
                case IdempotencyStartState.Conflict:
                    await transaction.RollbackAsync(cancellationToken);
                    return new DispatchTransactionResult(
                        new AsyncOperationDispatchResult(
                            AsyncOperationDispatchState.Conflict,
                            request.OperationId,
                            startResult.Record.CorrelationId,
                            new StoredHttpResponse(StatusCodes.Status409Conflict, string.Empty),
                            "operation_conflict",
                            "The same operationId was used with a different payload."),
                        null);

                case IdempotencyStartState.Completed:
                    await transaction.RollbackAsync(cancellationToken);
                    return new DispatchTransactionResult(
                        new AsyncOperationDispatchResult(
                            AsyncOperationDispatchState.Completed,
                            request.OperationId,
                            startResult.Record.CorrelationId,
                            new StoredHttpResponse(
                                startResult.Record.FinalHttpStatus ?? request.AcceptedStatusCode,
                                startResult.Record.FinalResponseJson ?? startResult.Record.AcceptedResponseJson ?? acceptedJson)),
                        null);

                case IdempotencyStartState.Failed:
                    await transaction.RollbackAsync(cancellationToken);
                    return new DispatchTransactionResult(
                        new AsyncOperationDispatchResult(
                            AsyncOperationDispatchState.Failed,
                            request.OperationId,
                            startResult.Record.CorrelationId,
                            new StoredHttpResponse(
                                startResult.Record.AcceptedHttpStatus ?? request.AcceptedStatusCode,
                                startResult.Record.AcceptedResponseJson ?? acceptedJson),
                            startResult.Record.ErrorCode,
                            startResult.Record.ErrorMessage),
                        null);

                case IdempotencyStartState.Processing:
                    await transaction.RollbackAsync(cancellationToken);
                    return new DispatchTransactionResult(
                        new AsyncOperationDispatchResult(
                            AsyncOperationDispatchState.Processing,
                            request.OperationId,
                            startResult.Record.CorrelationId,
                            new StoredHttpResponse(
                                startResult.Record.AcceptedHttpStatus ?? request.AcceptedStatusCode,
                                startResult.Record.AcceptedResponseJson ?? acceptedJson)),
                        null);

                case IdempotencyStartState.Started:
                    var @event = request.BuildEvent(startResult.Record.CorrelationId, request.OperationId, causationId);
                    var outboxMessage = await outboxService.EnqueueAsync(@event, request.RoutingKey, cancellationToken);
                    await transaction.CommitAsync(cancellationToken);
                    return new DispatchTransactionResult(
                        new AsyncOperationDispatchResult(
                            AsyncOperationDispatchState.Started,
                            request.OperationId,
                            startResult.Record.CorrelationId,
                            new StoredHttpResponse(request.AcceptedStatusCode, acceptedJson)),
                        outboxMessage.Id);

                default:
                    await transaction.RollbackAsync(cancellationToken);
                    return new DispatchTransactionResult(
                        new AsyncOperationDispatchResult(
                            AsyncOperationDispatchState.Failed,
                            request.OperationId,
                            startResult.Record.CorrelationId,
                            new StoredHttpResponse(request.AcceptedStatusCode, acceptedJson),
                            "unknown_state",
                            "Unexpected idempotency state."),
                        null);
            }
        });

        if (transactionResult.OutboxMessageId.HasValue)
        {
            _ = await outboxService.TryPublishAsync(transactionResult.OutboxMessageId.Value, cancellationToken);
        }

        return transactionResult.Result;
    }

    private sealed record DispatchTransactionResult(AsyncOperationDispatchResult Result, Guid? OutboxMessageId);
}

