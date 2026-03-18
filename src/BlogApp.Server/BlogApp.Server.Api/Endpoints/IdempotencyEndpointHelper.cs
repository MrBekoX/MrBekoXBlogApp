using System.Data;
using System.Text;
using System.Text.Json;
using BlogApp.Server.Application.Common.Interfaces.Persistence;
using BlogApp.Server.Application.Common.Interfaces.Services;
using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.Common.Utilities;
using Microsoft.AspNetCore.Http;
using Microsoft.Extensions.Primitives;

namespace BlogApp.Server.Api.Endpoints;

internal record SyncIdempotencyContext(string? CorrelationId)
{
    public bool IsActive => CorrelationId is not null;
}

internal sealed class SyncIdempotencyExecutionScope : IAsyncDisposable
{
    private readonly SyncIdempotencyContext _context;
    private ITransactionScope? _transaction;
    private bool _settled;

    public SyncIdempotencyExecutionScope(
        SyncIdempotencyContext context,
        ITransactionScope? transaction)
    {
        _context = context;
        _transaction = transaction;
    }

    public async Task CompleteAndCommitAsync(
        int statusCode,
        object response,
        IIdempotencyService idempotencyService,
        CancellationToken cancellationToken,
        HttpResponse? httpResponse = null)
    {
        await IdempotencyEndpointHelper.CompleteSyncRequest(
            _context,
            statusCode,
            response,
            idempotencyService,
            cancellationToken,
            httpResponse);

        await CommitTransactionAsync(cancellationToken);
    }

    public async Task FailAndCommitAsync(
        string errorCode,
        string errorMessage,
        IIdempotencyService idempotencyService,
        CancellationToken cancellationToken)
    {
        await IdempotencyEndpointHelper.FailSyncRequest(
            _context,
            errorCode,
            errorMessage,
            idempotencyService,
            cancellationToken);

        await CommitTransactionAsync(cancellationToken);
    }

    public async Task RollbackAsync(CancellationToken cancellationToken = default)
    {
        if (_settled)
        {
            return;
        }

        if (_transaction is not null)
        {
            await _transaction.RollbackAsync(cancellationToken);
        }

        _settled = true;
    }

    private async Task CommitTransactionAsync(CancellationToken cancellationToken)
    {
        if (_settled)
        {
            return;
        }

        if (_transaction is not null)
        {
            await _transaction.CommitAsync(cancellationToken);
        }

        _settled = true;
    }

    public async ValueTask DisposeAsync()
    {
        if (_transaction is not null)
        {
            await _transaction.DisposeAsync();
            _transaction = null;
        }

        _settled = true;
    }
}

internal static class IdempotencyEndpointHelper
{
    public static bool TryResolveOperationId(
        HttpContext httpContext,
        string? requestOperationId,
        out string operationId,
        out IResult? errorResult)
    {
        return TryResolveOperationId(httpContext, requestOperationId, requireHeader: false, out operationId, out errorResult);
    }

    public static bool TryResolveOperationId(
        HttpContext httpContext,
        string? requestOperationId,
        bool requireHeader,
        out string operationId,
        out IResult? errorResult)
    {
        var headerOperationId = httpContext.Request.Headers["Idempotency-Key"].FirstOrDefault();

        if (requireHeader && string.IsNullOrWhiteSpace(headerOperationId))
        {
            operationId = string.Empty;
            errorResult = Results.BadRequest(ApiResponse<object>.FailureResult("Idempotency-Key header is required."));
            return false;
        }

        if (!string.IsNullOrWhiteSpace(requestOperationId)
            && !string.IsNullOrWhiteSpace(headerOperationId)
            && !string.Equals(requestOperationId, headerOperationId, StringComparison.Ordinal))
        {
            operationId = string.Empty;
            errorResult = Results.BadRequest(ApiResponse<object>.FailureResult("operationId body value and Idempotency-Key header must match."));
            return false;
        }

        operationId = !string.IsNullOrWhiteSpace(requestOperationId)
            ? requestOperationId.Trim()
            : (headerOperationId ?? string.Empty).Trim();

        if (string.IsNullOrWhiteSpace(operationId))
        {
            errorResult = Results.BadRequest(ApiResponse<object>.FailureResult("operationId is required."));
            return false;
        }

        errorResult = null;
        return true;
    }

    public static IResult BuildStoredResponse(StoredHttpResponse response)
    {
        return new StoredHttpResponseResult(response);
    }

    public static IResult BuildProcessingAccepted(string operationId, string? correlationId, string message)
    {
        return Results.Accepted(value: ApiResponse<object>.SuccessResult(
            new
            {
                operationId,
                correlationId,
                status = "Processing"
            },
            message));
    }

    public static IResult BuildConflict(string message)
    {
        return Results.Conflict(ApiResponse<object>.FailureResult(message));
    }

    public static async Task<(bool ShouldProceed, IResult? EarlyReturn, SyncIdempotencyContext Context)> TryBeginSyncRequest(
        HttpContext httpContext,
        string endpointName,
        object requestPayload,
        IIdempotencyService idempotencyService,
        ICurrentUserService currentUserService,
        CancellationToken cancellationToken,
        bool requireIdempotencyKey = false,
        string? requestHash = null,
        string? requestOperationId = null)
    {
        if (!TryResolveOperationId(httpContext, requestOperationId, requireIdempotencyKey, out var operationId, out var errorResult))
        {
            return (false, errorResult, new SyncIdempotencyContext(null));
        }

        if (string.IsNullOrWhiteSpace(operationId))
        {
            return (true, null, new SyncIdempotencyContext(null));
        }

        var correlationId = Guid.NewGuid().ToString();
        var resolvedRequestHash = requestHash ?? IdempotencyRequestHasher.Compute(requestPayload);

        var startResult = await idempotencyService.BeginRequestAsync(
            new IdempotencyStartRequest(
                endpointName,
                operationId,
                resolvedRequestHash,
                correlationId,
                currentUserService.CorrelationId,
                0,
                null,
                currentUserService.UserId,
                null,
                null),
            cancellationToken);

        return startResult.State switch
        {
            IdempotencyStartState.Started =>
                (true, null, new SyncIdempotencyContext(correlationId)),

            IdempotencyStartState.Completed when startResult.Record.FinalResponseJson is not null =>
                (false, BuildStoredResponse(new StoredHttpResponse(
                    startResult.Record.FinalHttpStatus ?? StatusCodes.Status200OK,
                    startResult.Record.FinalResponseJson,
                    DeserializeHeaders(startResult.Record.FinalResponseHeadersJson))), new SyncIdempotencyContext(null)),

            IdempotencyStartState.Processing =>
                (false, Results.Conflict(ApiResponse<object>.FailureResult(
                    "This operation is already being processed. Retry with a new Idempotency-Key.")),
                    new SyncIdempotencyContext(null)),

            IdempotencyStartState.Failed =>
                (false, Results.UnprocessableEntity(ApiResponse<object>.FailureResult(
                    startResult.Record.ErrorMessage ?? "Previous attempt failed. Retry with a new Idempotency-Key.")),
                    new SyncIdempotencyContext(null)),

            IdempotencyStartState.Conflict =>
                (false, BuildConflict("The same Idempotency-Key was used with a different payload."),
                    new SyncIdempotencyContext(null)),

            _ => (true, null, new SyncIdempotencyContext(correlationId))
        };
    }

    public static async Task<(bool ShouldProceed, IResult? EarlyReturn, SyncIdempotencyExecutionScope Scope)> TryBeginTransactionalSyncRequest(
        HttpContext httpContext,
        string endpointName,
        object requestPayload,
        IUnitOfWork unitOfWork,
        IIdempotencyService idempotencyService,
        ICurrentUserService currentUserService,
        CancellationToken cancellationToken,
        bool requireIdempotencyKey = false,
        string? requestHash = null,
        string? requestOperationId = null)
    {
        var transaction = await unitOfWork.BeginTransactionAsync(IsolationLevel.ReadCommitted, cancellationToken);

        try
        {
            var (shouldProceed, earlyReturn, context) = await TryBeginSyncRequest(
                httpContext,
                endpointName,
                requestPayload,
                idempotencyService,
                currentUserService,
                cancellationToken,
                requireIdempotencyKey,
                requestHash,
                requestOperationId);

            if (!shouldProceed)
            {
                await transaction.DisposeAsync();
                return (false, earlyReturn, new SyncIdempotencyExecutionScope(new SyncIdempotencyContext(null), null));
            }

            return (true, null, new SyncIdempotencyExecutionScope(context, transaction));
        }
        catch
        {
            await transaction.DisposeAsync();
            throw;
        }
    }

    public static async Task CompleteSyncRequest(
        SyncIdempotencyContext context,
        int statusCode,
        object response,
        IIdempotencyService idempotencyService,
        CancellationToken cancellationToken,
        HttpResponse? httpResponse = null)
    {
        if (context.IsActive)
        {
            await idempotencyService.MarkCompletedByCorrelationAsync(
                context.CorrelationId!,
                statusCode,
                response,
                cancellationToken,
                CaptureReplayableHeaders(httpResponse?.Headers));
        }
    }

    public static async Task FailSyncRequest(
        SyncIdempotencyContext context,
        string errorCode,
        string errorMessage,
        IIdempotencyService idempotencyService,
        CancellationToken cancellationToken)
    {
        if (context.IsActive)
        {
            await idempotencyService.MarkFailedByCorrelationAsync(
                context.CorrelationId!,
                errorCode,
                errorMessage,
                cancellationToken);
        }
    }

    public static string CreateHeaderOnlyRequestHash(string endpointName, string? principalValue, string? ipAddress)
    {
        var principalHash = string.IsNullOrWhiteSpace(principalValue)
            ? "none"
            : IdempotencyRequestHasher.Compute(new { Value = principalValue.Trim() });

        return IdempotencyRequestHasher.Compute(new
        {
            endpointName,
            principalHash,
            ipAddress = ipAddress?.Trim() ?? string.Empty
        });
    }

    private static IReadOnlyDictionary<string, string[]>? CaptureReplayableHeaders(IHeaderDictionary? headers)
    {
        if (headers is null || headers.Count == 0)
        {
            return null;
        }

        var captured = new Dictionary<string, string[]>(StringComparer.OrdinalIgnoreCase);

        foreach (var header in headers)
        {
            if (!ShouldReplayHeader(header.Key, header.Value))
            {
                continue;
            }

            captured[header.Key] = header.Value
                .Where(static value => value is not null)
                .Select(static value => value!)
                .ToArray();
        }

        return captured.Count == 0 ? null : captured;
    }

    private static bool ShouldReplayHeader(string key, StringValues values)
    {
        if (values.Count == 0)
        {
            return false;
        }

        return !key.Equals("Content-Length", StringComparison.OrdinalIgnoreCase)
            && !key.Equals("Date", StringComparison.OrdinalIgnoreCase)
            && !key.Equals("Server", StringComparison.OrdinalIgnoreCase)
            && !key.Equals("Transfer-Encoding", StringComparison.OrdinalIgnoreCase);
    }

    private static IReadOnlyDictionary<string, string[]>? DeserializeHeaders(string? json)
    {
        if (string.IsNullOrWhiteSpace(json))
        {
            return null;
        }

        return JsonSerializer.Deserialize<Dictionary<string, string[]>>(json);
    }

    private sealed class StoredHttpResponseResult(StoredHttpResponse response) : IResult
    {
        public async Task ExecuteAsync(HttpContext httpContext)
        {
            httpContext.Response.StatusCode = response.StatusCode;

            if (response.Headers is not null)
            {
                foreach (var header in response.Headers)
                {
                    if (header.Key.Equals("Content-Type", StringComparison.OrdinalIgnoreCase))
                    {
                        httpContext.Response.ContentType = header.Value.FirstOrDefault() ?? response.ContentType;
                        continue;
                    }

                    httpContext.Response.Headers.Remove(header.Key);
                    httpContext.Response.Headers.Append(header.Key, header.Value);
                }
            }

            httpContext.Response.ContentType ??= response.ContentType;

            if (response.StatusCode is StatusCodes.Status204NoContent or StatusCodes.Status304NotModified)
            {
                return;
            }

            if (!string.IsNullOrEmpty(response.Json))
            {
                await httpContext.Response.WriteAsync(response.Json, Encoding.UTF8);
            }
        }
    }
}
