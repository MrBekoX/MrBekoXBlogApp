using System.Text.Json;
using BlogApp.BuildingBlocks.Messaging.Abstractions;
using BlogApp.Server.Application.Common.Constants;
using BlogApp.Server.Application.Common.Interfaces.Services;
using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.Common.Utilities;
using BlogApp.Server.Infrastructure.Persistence;
using Microsoft.AspNetCore.Http;
using Microsoft.EntityFrameworkCore;

namespace BlogApp.Server.Infrastructure.Services;

public class AiGenerationRequestExecutor(
    AppDbContext context,
    IIdempotencyService idempotencyService,
    IOutboxService outboxService,
    ICurrentUserService currentUserService) : IAiGenerationRequestExecutor
{
    private static readonly JsonSerializerOptions SerializerOptions = new()
    {
        PropertyNameCaseInsensitive = true
    };

    public async Task<AiGenerationExecutionResult<TResult>> ExecuteAsync<TEvent, TResult>(
        AiGenerationExecutionRequest<TEvent> request,
        CancellationToken cancellationToken = default)
        where TEvent : IIntegrationEvent
    {
        if (!outboxService.IsEnabled)
        {
            return new AiGenerationExecutionResult<TResult>(
                AiGenerationExecutionState.Failed,
                request.OperationId,
                string.Empty,
                default,
                AsyncOperationErrorCodes.AsyncDispatchUnavailable,
                "Asynchronous processing is temporarily unavailable.");
        }

        var requestHash = IdempotencyRequestHasher.Compute(request.RequestPayload);
        var correlationId = Guid.NewGuid().ToString();
        var causationId = currentUserService.CorrelationId;
        var acceptedJson = JsonSerializer.Serialize(
            new
            {
                operationId = request.OperationId,
                correlationId,
                status = "processing"
            });

        var strategy = context.Database.CreateExecutionStrategy();
        var stageResult = await strategy.ExecuteAsync(async () =>
        {
            await using var transaction = await context.Database.BeginTransactionAsync(cancellationToken);
            var startResult = await idempotencyService.BeginRequestAsync(
                new IdempotencyStartRequest(
                    request.EndpointName,
                    request.OperationId,
                    requestHash,
                    correlationId,
                    causationId,
                    StatusCodes.Status202Accepted,
                    acceptedJson,
                    request.UserId,
                    SessionId: null,
                    request.ResourceId),
                cancellationToken);

            switch (startResult.State)
            {
                case IdempotencyStartState.Conflict:
                    await transaction.RollbackAsync(cancellationToken);
                    return new AiGenerationStageResult<TResult>(
                        new AiGenerationExecutionResult<TResult>(
                            AiGenerationExecutionState.Conflict,
                            request.OperationId,
                            startResult.Record.CorrelationId,
                            default,
                            "operation_conflict",
                            "The same operationId was used with a different payload."),
                        null);

                case IdempotencyStartState.Completed:
                    await transaction.RollbackAsync(cancellationToken);
                    return new AiGenerationStageResult<TResult>(
                        new AiGenerationExecutionResult<TResult>(
                            AiGenerationExecutionState.Completed,
                            request.OperationId,
                            startResult.Record.CorrelationId,
                            DeserializeResult<TResult>(startResult.Record.FinalResponseJson)),
                        null);

                case IdempotencyStartState.Failed:
                    await transaction.RollbackAsync(cancellationToken);
                    return new AiGenerationStageResult<TResult>(
                        new AiGenerationExecutionResult<TResult>(
                            AiGenerationExecutionState.Failed,
                            request.OperationId,
                            startResult.Record.CorrelationId,
                            default,
                            startResult.Record.ErrorCode,
                            startResult.Record.ErrorMessage),
                        null);

                case IdempotencyStartState.Processing:
                    await transaction.RollbackAsync(cancellationToken);
                    return new AiGenerationStageResult<TResult>(
                        new AiGenerationExecutionResult<TResult>(
                            AiGenerationExecutionState.Processing,
                            request.OperationId,
                            startResult.Record.CorrelationId,
                            default),
                        null);

                case IdempotencyStartState.Started:
                    var @event = request.BuildEvent(startResult.Record.CorrelationId, request.OperationId, causationId);
                    var outboxMessage = await outboxService.EnqueueAsync(@event, request.RoutingKey, cancellationToken);
                    await transaction.CommitAsync(cancellationToken);
                    return new AiGenerationStageResult<TResult>(
                        new AiGenerationExecutionResult<TResult>(
                            AiGenerationExecutionState.Processing,
                            request.OperationId,
                            startResult.Record.CorrelationId,
                            default),
                        outboxMessage.Id);

                default:
                    await transaction.RollbackAsync(cancellationToken);
                    return new AiGenerationStageResult<TResult>(
                        new AiGenerationExecutionResult<TResult>(
                            AiGenerationExecutionState.Failed,
                            request.OperationId,
                            startResult.Record.CorrelationId,
                            default,
                            "unknown_state",
                            "Unexpected idempotency state."),
                        null);
            }
        });

        if (stageResult.OutboxMessageId.HasValue)
        {
            _ = await outboxService.TryPublishAsync(stageResult.OutboxMessageId.Value, cancellationToken);
        }

        return stageResult.ImmediateResult;
    }

    private static TResult? DeserializeResult<TResult>(string? json)
    {
        if (string.IsNullOrWhiteSpace(json))
        {
            return default;
        }

        return JsonSerializer.Deserialize<TResult>(json, SerializerOptions);
    }

    private sealed record AiGenerationStageResult<TResult>(
        AiGenerationExecutionResult<TResult> ImmediateResult,
        Guid? OutboxMessageId);
}
