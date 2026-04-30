using System.Text;
using BlogApp.Server.Application.Common.Models;

namespace BlogApp.Server.Api.Helpers;

/// <summary>
/// Static helper for idempotency-related operations in endpoints.
/// Handles Idempotency-Key header resolution and common response builders.
/// </summary>
public static class IdempotencyHelper
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
