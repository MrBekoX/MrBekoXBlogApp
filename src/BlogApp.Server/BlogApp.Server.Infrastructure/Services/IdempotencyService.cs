using Microsoft.Extensions.Logging;
using System.Text.Json;
using System.Text.Json.Serialization;
using BlogApp.Server.Application.Common.Interfaces.Services;
using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Domain.Entities;
using BlogApp.Server.Domain.Enums;
using BlogApp.Server.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;
using Npgsql;

namespace BlogApp.Server.Infrastructure.Services;

public class IdempotencyService(
    AppDbContext context,
    ILogger<IdempotencyService> logger) : IIdempotencyService
{
    private static readonly JsonSerializerOptions SerializerOptions = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
        WriteIndented = false
    };

    public async Task<IdempotencyStartResult> BeginRequestAsync(
        IdempotencyStartRequest request,
        CancellationToken cancellationToken = default)
    {
        var existing = await context.IdempotencyRecords
            .SingleOrDefaultAsync(
                x => x.EndpointName == request.EndpointName && x.OperationId == request.OperationId,
                cancellationToken);

        if (existing is not null)
        {
            return BuildExistingStartResult(existing, request.RequestHash);
        }

        var record = new IdempotencyRecord
        {
            EndpointName = request.EndpointName,
            OperationId = request.OperationId,
            RequestHash = request.RequestHash,
            CorrelationId = request.CorrelationId,
            CausationId = request.CausationId,
            AcceptedHttpStatus = request.AcceptedHttpStatus,
            AcceptedResponseJson = string.IsNullOrWhiteSpace(request.AcceptedResponseJson) ? null : request.AcceptedResponseJson,
            UserId = request.UserId,
            SessionId = request.SessionId,
            ResourceId = request.ResourceId,
            Status = IdempotencyRecordStatus.Processing
        };

        context.IdempotencyRecords.Add(record);

        try
        {
            await context.SaveChangesAsync(cancellationToken);
            return new IdempotencyStartResult(IdempotencyStartState.Started, record);
        }
        catch (DbUpdateException ex)
        {
            if (!IsUniqueConstraintViolation(ex))
            {
                throw;
            }

            logger.LogWarning(ex, "Idempotency insert race for {EndpointName}/{OperationId}", request.EndpointName, request.OperationId);
            context.Entry(record).State = EntityState.Detached;

            existing = await context.IdempotencyRecords
                .SingleOrDefaultAsync(
                    x => x.EndpointName == request.EndpointName && x.OperationId == request.OperationId,
                    cancellationToken);

            if (existing is null)
            {
                throw;
            }

            return BuildExistingStartResult(existing, request.RequestHash);
        }
    }

    public Task<IdempotencyRecord?> GetRequestByOperationAsync(
        string endpointName,
        string operationId,
        CancellationToken cancellationToken = default)
    {
        return context.IdempotencyRecords
            .AsNoTracking()
            .SingleOrDefaultAsync(
                x => x.EndpointName == endpointName && x.OperationId == operationId,
                cancellationToken);
    }

    public Task<IdempotencyRecord?> GetRequestByCorrelationIdAsync(
        string correlationId,
        CancellationToken cancellationToken = default)
    {
        return context.IdempotencyRecords
            .SingleOrDefaultAsync(x => x.CorrelationId == correlationId, cancellationToken);
    }

    public async Task MarkCompletedByCorrelationAsync(
        string correlationId,
        int finalHttpStatus,
        object finalResponse,
        CancellationToken cancellationToken = default,
        IReadOnlyDictionary<string, string[]>? finalResponseHeaders = null)
    {
        var record = await context.IdempotencyRecords
            .SingleOrDefaultAsync(x => x.CorrelationId == correlationId, cancellationToken);

        if (record is null)
        {
            logger.LogWarning("No idempotency record found for correlation {CorrelationId}", correlationId);
            return;
        }

        record.Status = IdempotencyRecordStatus.Completed;
        record.FinalHttpStatus = finalHttpStatus;
        record.FinalResponseJson = JsonSerializer.Serialize(finalResponse, finalResponse.GetType(), SerializerOptions);
        record.FinalResponseHeadersJson = SerializeHeaders(finalResponseHeaders);
        record.CompletedAt = DateTime.UtcNow;
        record.ErrorCode = null;
        record.ErrorMessage = null;

        await context.SaveChangesAsync(cancellationToken);
    }

    public async Task MarkFailedByCorrelationAsync(
        string correlationId,
        string errorCode,
        string errorMessage,
        CancellationToken cancellationToken = default)
    {
        var record = await context.IdempotencyRecords
            .SingleOrDefaultAsync(x => x.CorrelationId == correlationId, cancellationToken);

        if (record is null)
        {
            logger.LogWarning("No idempotency record found for failed correlation {CorrelationId}", correlationId);
            return;
        }

        record.Status = IdempotencyRecordStatus.Failed;
        record.ErrorCode = errorCode;
        record.ErrorMessage = errorMessage;
        record.CompletedAt = DateTime.UtcNow;

        await context.SaveChangesAsync(cancellationToken);
    }

    public async Task<ConsumerClaimResult> ClaimConsumerAsync(
        string consumerName,
        string operationId,
        Guid? messageId,
        string? correlationId,
        CancellationToken cancellationToken = default)
    {
        var existing = await context.ConsumerInboxMessages
            .SingleOrDefaultAsync(
                x => x.ConsumerName == consumerName && x.OperationId == operationId,
                cancellationToken);

        if (existing is not null)
        {
            var state = existing.Status switch
            {
                ConsumerInboxStatus.Completed => ConsumerClaimState.DuplicateCompleted,
                ConsumerInboxStatus.Failed => ConsumerClaimState.Failed,
                _ => ConsumerClaimState.DuplicateProcessing
            };

            return new ConsumerClaimResult(state, existing);
        }

        var record = new ConsumerInboxMessage
        {
            ConsumerName = consumerName,
            OperationId = operationId,
            MessageId = messageId,
            CorrelationId = correlationId,
            Status = ConsumerInboxStatus.Processing
        };

        context.ConsumerInboxMessages.Add(record);

        try
        {
            await context.SaveChangesAsync(cancellationToken);
            return new ConsumerClaimResult(ConsumerClaimState.Claimed, record);
        }
        catch (DbUpdateException ex)
        {
            if (!IsUniqueConstraintViolation(ex))
            {
                throw;
            }

            logger.LogWarning(ex, "Consumer inbox insert race for {ConsumerName}/{OperationId}", consumerName, operationId);
            context.Entry(record).State = EntityState.Detached;

            existing = await context.ConsumerInboxMessages
                .SingleOrDefaultAsync(
                    x => x.ConsumerName == consumerName && x.OperationId == operationId,
                    cancellationToken);

            if (existing is null)
            {
                throw;
            }

            var state = existing.Status == ConsumerInboxStatus.Completed
                ? ConsumerClaimState.DuplicateCompleted
                : ConsumerClaimState.DuplicateProcessing;

            return new ConsumerClaimResult(state, existing);
        }
    }

    public async Task MarkConsumerCompletedAsync(Guid inboxId, CancellationToken cancellationToken = default)
    {
        var record = await context.ConsumerInboxMessages
            .SingleOrDefaultAsync(x => x.Id == inboxId, cancellationToken);

        if (record is null)
        {
            return;
        }

        record.Status = ConsumerInboxStatus.Completed;
        record.ProcessedAt = DateTime.UtcNow;
        record.LastError = null;

        await context.SaveChangesAsync(cancellationToken);
    }

    public async Task MarkConsumerFailedAsync(Guid inboxId, string error, CancellationToken cancellationToken = default)
    {
        var record = await context.ConsumerInboxMessages
            .SingleOrDefaultAsync(x => x.Id == inboxId, cancellationToken);

        if (record is null)
        {
            return;
        }

        record.Status = ConsumerInboxStatus.Failed;
        record.LastError = error;
        record.ProcessedAt = DateTime.UtcNow;

        await context.SaveChangesAsync(cancellationToken);
    }

    private static string? SerializeHeaders(IReadOnlyDictionary<string, string[]>? headers)
    {
        if (headers is null || headers.Count == 0)
        {
            return null;
        }

        var normalized = headers
            .Where(static entry => entry.Value.Length > 0)
            .ToDictionary(static entry => entry.Key, static entry => entry.Value);

        return normalized.Count == 0
            ? null
            : JsonSerializer.Serialize(normalized, SerializerOptions);
    }

    private static IdempotencyStartResult BuildExistingStartResult(IdempotencyRecord existing, string requestHash)
    {
        if (!string.Equals(existing.RequestHash, requestHash, StringComparison.Ordinal))
        {
            return new IdempotencyStartResult(IdempotencyStartState.Conflict, existing);
        }

        var state = existing.Status switch
        {
            IdempotencyRecordStatus.Completed => IdempotencyStartState.Completed,
            IdempotencyRecordStatus.Failed => IdempotencyStartState.Failed,
            _ => IdempotencyStartState.Processing
        };

        return new IdempotencyStartResult(state, existing);
    }

    private static bool IsUniqueConstraintViolation(DbUpdateException ex)
        => ex.InnerException is PostgresException { SqlState: PostgresErrorCodes.UniqueViolation };
}

