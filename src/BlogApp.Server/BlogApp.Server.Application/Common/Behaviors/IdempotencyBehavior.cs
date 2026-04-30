using System.ComponentModel.DataAnnotations;
using System.Data;
using System.Text.Json;
using BlogApp.Server.Application.Common.Interfaces;
using BlogApp.Server.Application.Common.Interfaces.Persistence;
using BlogApp.Server.Application.Common.Interfaces.Services;
using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.Common.Utilities;
using MediatR;
using Microsoft.Extensions.Logging;

namespace BlogApp.Server.Application.Common.Behaviors;

/// <summary>
/// MediatR pipeline behavior that provides automatic idempotency with transaction management
/// for commands implementing <see cref="IIdempotentCommand"/>.
///
/// Lifecycle:
/// 1. BeginTransaction(ReadCommitted)
/// 2. BeginRequest (idempotency check)
///    → Completed → deserialize cached response, commit, return
///    → Processing/Failed/Conflict → rollback, throw
///    → Started → proceed
/// 3. next() — handler executes within the transaction
/// 4. Success → MarkCompleted + Commit
/// 5. Failure (Result.IsFailure) → MarkFailed + Commit
/// 6. Exception → Rollback + rethrow
/// </summary>
public class IdempotencyBehavior<TRequest, TResponse> : IPipelineBehavior<TRequest, TResponse>
    where TRequest : IIdempotentCommand
{
    private readonly IIdempotencyService _idempotencyService;
    private readonly ICurrentUserService _currentUserService;
    private readonly IUnitOfWork _unitOfWork;
    private readonly ILogger<IdempotencyBehavior<TRequest, TResponse>> _logger;

    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        PropertyNameCaseInsensitive = true,
        WriteIndented = false
    };

    public IdempotencyBehavior(
        IIdempotencyService idempotencyService,
        ICurrentUserService currentUserService,
        IUnitOfWork unitOfWork,
        ILogger<IdempotencyBehavior<TRequest, TResponse>> logger)
    {
        _idempotencyService = idempotencyService;
        _currentUserService = currentUserService;
        _unitOfWork = unitOfWork;
        _logger = logger;
    }

    public async Task<TResponse> Handle(
        TRequest request,
        RequestHandlerDelegate<TResponse> next,
        CancellationToken cancellationToken)
    {
        if (string.IsNullOrWhiteSpace(request.OperationId))
        {
            throw new ValidationException("Idempotency-Key header is required.");
        }

        var endpointName = request.IdempotencyEndpointName;
        var operationId = request.OperationId.Trim();
        var requestHash = request.CustomRequestHash ?? IdempotencyRequestHasher.Compute(request);
        var correlationId = _currentUserService.CorrelationId ?? Guid.NewGuid().ToString();

        // Wrap in ExecuteResilientAsync to work with NpgsqlRetryingExecutionStrategy
        return await _unitOfWork.ExecuteResilientAsync(async (ct) =>
        {
            // 1. Begin transaction
            var transaction = await _unitOfWork.BeginTransactionAsync(
                IsolationLevel.ReadCommitted, ct);

            try
            {
                // 2. Idempotency check
                var startResult = await _idempotencyService.BeginRequestAsync(
                    new IdempotencyStartRequest(
                        EndpointName: endpointName,
                        OperationId: operationId,
                        RequestHash: requestHash,
                        CorrelationId: correlationId,
                        CausationId: _currentUserService.CorrelationId,
                        AcceptedHttpStatus: 0,
                        AcceptedResponseJson: null,
                        UserId: _currentUserService.UserId,
                        SessionId: null,
                        ResourceId: null),
                    ct);

                switch (startResult.State)
                {
                    case IdempotencyStartState.Completed:
                        _logger.LogInformation(
                            "[Idempotency] Duplicate {OperationId} for {Endpoint} — returning cached result",
                            operationId, endpointName);
                        await transaction.CommitAsync(ct);
                        return DeserializeCachedResponse(startResult.Record.FinalResponseJson);

                    case IdempotencyStartState.Processing:
                        await transaction.RollbackAsync(ct);
                        throw new InvalidOperationException(
                            $"Operation {operationId} is already being processed. Retry with a new Idempotency-Key.");

                    case IdempotencyStartState.Failed:
                        await transaction.RollbackAsync(ct);
                        throw new InvalidOperationException(
                            startResult.Record.ErrorMessage ?? "Previous attempt failed. Retry with a new Idempotency-Key.");

                    case IdempotencyStartState.Conflict:
                        await transaction.RollbackAsync(ct);
                        throw new InvalidOperationException(
                            "The same Idempotency-Key was used with a different payload.");
                }

                // 3. Execute handler within transaction
                var response = await next();

                // 4. Check Result pattern — if response has a Result property, inspect it
                var failed = TryExtractFailure(response, out var errorMessage);

                if (failed)
                {
                    await _idempotencyService.MarkFailedByCorrelationAsync(
                        correlationId, "handler_failure", errorMessage!, ct);
                    await transaction.CommitAsync(ct);

                    _logger.LogInformation(
                        "[Idempotency] Failed {OperationId} for {Endpoint}: {Error}",
                        operationId, endpointName, errorMessage);

                    return response;
                }

                // 5. Mark completed + commit
                await _idempotencyService.MarkCompletedByCorrelationAsync(
                    correlationId, 200, response!, ct);
                await transaction.CommitAsync(ct);

                _logger.LogInformation(
                    "[Idempotency] Completed {OperationId} for {Endpoint}",
                    operationId, endpointName);

                return response;
            }
            catch (Exception ex) when (ex is not ValidationException and not InvalidOperationException)
            {
                await transaction.RollbackAsync(ct);

                try
                {
                    await _idempotencyService.MarkFailedByCorrelationAsync(
                        correlationId, "handler_error", ex.Message, ct);
                }
                catch (Exception markEx)
                {
                    _logger.LogWarning(markEx,
                        "[Idempotency] Failed to mark error for {OperationId}", operationId);
                }

                _logger.LogError(ex,
                    "[Idempotency] Exception in {OperationId} for {Endpoint}",
                    operationId, endpointName);

                throw;
            }
            finally
            {
                await transaction.DisposeAsync();
            }
        }, cancellationToken);
    }

    private TResponse DeserializeCachedResponse(string? json)
    {
        if (string.IsNullOrWhiteSpace(json))
        {
            return default!;
        }

        try
        {
            return JsonSerializer.Deserialize<TResponse>(json, JsonOptions)!;
        }
        catch (JsonException ex)
        {
            _logger.LogWarning(ex, "[Idempotency] Failed to deserialize cached response");
            return default!;
        }
    }

    /// <summary>
    /// Uses reflection to check if TResponse has a Result property with IsFailure.
    /// This avoids requiring a base class/interface on all response types.
    /// </summary>
    private static bool TryExtractFailure(TResponse response, out string? errorMessage)
    {
        errorMessage = null;
        if (response is null) return false;

        var resultProp = typeof(TResponse).GetProperty("Result");
        if (resultProp is null) return false;

        var resultValue = resultProp.GetValue(response);
        if (resultValue is null) return false;

        var isFailureProp = resultValue.GetType().GetProperty("IsFailure");
        if (isFailureProp is null) return false;

        var isFailure = (bool)(isFailureProp.GetValue(resultValue) ?? false);
        if (!isFailure) return false;

        var errorProp = resultValue.GetType().GetProperty("Error");
        errorMessage = errorProp?.GetValue(resultValue) as string ?? "Unknown error";
        return true;
    }
}
