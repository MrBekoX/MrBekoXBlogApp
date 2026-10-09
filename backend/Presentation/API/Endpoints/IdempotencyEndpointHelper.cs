using System.Text;
using System.Text.Json;
using BlogApp.Core.Application.Common.Models;
using BlogApp.Core.Application.Common.Utilities;
using Microsoft.Extensions.Primitives;

namespace BlogApp.Presentation.Api.Endpoints;

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
                return;

            if (!string.IsNullOrEmpty(response.Json))
                await httpContext.Response.WriteAsync(response.Json, Encoding.UTF8);
        }
    }
}
