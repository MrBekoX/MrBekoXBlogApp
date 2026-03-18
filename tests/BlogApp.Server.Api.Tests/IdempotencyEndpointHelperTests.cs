using BlogApp.Server.Api.Endpoints;
using BlogApp.Server.Application.Common.Interfaces.Persistence;
using BlogApp.Server.Application.Common.Interfaces.Services;
using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Domain.Entities;
using Microsoft.AspNetCore.Http;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Primitives;

namespace BlogApp.Server.Api.Tests;

public class IdempotencyEndpointHelperTests
{
    [Fact]
    public async Task TryResolveOperationId_WhenHeaderRequiredAndMissing_ReturnsBadRequest()
    {
        var httpContext = new DefaultHttpContext();

        var resolved = IdempotencyEndpointHelper.TryResolveOperationId(
            httpContext,
            requestOperationId: null,
            requireHeader: true,
            out var operationId,
            out var errorResult);

        Assert.False(resolved);
        Assert.Equal(string.Empty, operationId);
        Assert.NotNull(errorResult);

        var responseContext = CreateResponseContext();
        await errorResult!.ExecuteAsync(responseContext);

        Assert.Equal(StatusCodes.Status400BadRequest, responseContext.Response.StatusCode);
        responseContext.Response.Body.Position = 0;
        using var reader = new StreamReader(responseContext.Response.Body);
        var body = await reader.ReadToEndAsync();
        Assert.Contains("Idempotency-Key header is required", body, StringComparison.Ordinal);
    }

    [Fact]
    public async Task TryResolveOperationId_WhenBodyAndHeaderMismatch_ReturnsBadRequest()
    {
        var httpContext = new DefaultHttpContext();
        httpContext.Request.Headers["Idempotency-Key"] = "header-op";

        var resolved = IdempotencyEndpointHelper.TryResolveOperationId(
            httpContext,
            requestOperationId: "body-op",
            requireHeader: true,
            out var operationId,
            out var errorResult);

        Assert.False(resolved);
        Assert.Equal(string.Empty, operationId);
        Assert.NotNull(errorResult);

        var responseContext = CreateResponseContext();
        await errorResult!.ExecuteAsync(responseContext);

        Assert.Equal(StatusCodes.Status400BadRequest, responseContext.Response.StatusCode);
        responseContext.Response.Body.Position = 0;
        using var reader = new StreamReader(responseContext.Response.Body);
        var body = await reader.ReadToEndAsync();
        Assert.Contains("must match", body, StringComparison.Ordinal);
    }

    [Fact]
    public async Task TryBeginSyncRequest_WhenSyncEndpointStarts_DoesNotUseEmptyJsonPlaceholder()
    {
        var httpContext = new DefaultHttpContext();
        httpContext.Request.Headers["Idempotency-Key"] = "upload-op-1";
        var idempotencyService = new RecordingIdempotencyService();
        var currentUserService = new RecordingCurrentUserService();

        var result = await IdempotencyEndpointHelper.TryBeginSyncRequest(
            httpContext,
            endpointName: "UploadImage",
            requestPayload: new { fileName = "hero.webp", length = 42 },
            idempotencyService,
            currentUserService,
            CancellationToken.None,
            requireIdempotencyKey: true,
            requestHash: "req-hash-1");

        Assert.True(result.ShouldProceed);
        Assert.Null(result.EarlyReturn);
        Assert.NotNull(result.Context.CorrelationId);
        Assert.NotNull(idempotencyService.LastRequest);
        Assert.Null(idempotencyService.LastRequest!.AcceptedResponseJson);
    }

    [Fact]
    public async Task BuildStoredResponse_ReplaysStoredHeaders()
    {
        var responseContext = new DefaultHttpContext();
        responseContext.Response.Body = new MemoryStream();

        var result = IdempotencyEndpointHelper.BuildStoredResponse(new StoredHttpResponse(
            StatusCodes.Status200OK,
            "{\"success\":true}",
            new Dictionary<string, string[]>
            {
                ["Set-Cookie"] = ["accessToken=abc; path=/", "refreshToken=def; path=/"],
                ["Location"] = ["/api/v1/auth/login"]
            }));

        await result.ExecuteAsync(responseContext);

        Assert.Equal(StatusCodes.Status200OK, responseContext.Response.StatusCode);
        Assert.Equal("application/json; charset=utf-8", responseContext.Response.ContentType);
        Assert.Equal(2, responseContext.Response.Headers["Set-Cookie"].Count);
        Assert.Equal("/api/v1/auth/login", responseContext.Response.Headers.Location.ToString());
        responseContext.Response.Body.Position = 0;
        using var reader = new StreamReader(responseContext.Response.Body);
        var body = await reader.ReadToEndAsync();
        Assert.Equal("{\"success\":true}", body);
    }

    [Fact]
    public async Task CompleteSyncRequest_CapturesReplayableHeaders()
    {
        var idempotencyService = new RecordingIdempotencyService();
        var responseContext = new DefaultHttpContext();
        responseContext.Response.Headers.Append("Set-Cookie", new StringValues(new[] { "accessToken=abc; path=/" }));
        responseContext.Response.Headers["Content-Length"] = "128";

        await IdempotencyEndpointHelper.CompleteSyncRequest(
            new SyncIdempotencyContext("corr-123"),
            StatusCodes.Status200OK,
            new { success = true },
            idempotencyService,
            CancellationToken.None,
            responseContext.Response);

        Assert.NotNull(idempotencyService.CompletedHeaders);
        Assert.True(idempotencyService.CompletedHeaders!.ContainsKey("Set-Cookie"));
        Assert.False(idempotencyService.CompletedHeaders.ContainsKey("Content-Length"));
    }

    [Fact]
    public void CreateHeaderOnlyRequestHash_ChangesWhenPrincipalChanges()
    {
        var first = IdempotencyEndpointHelper.CreateHeaderOnlyRequestHash("AuthRefreshToken", "token-1", "127.0.0.1");
        var second = IdempotencyEndpointHelper.CreateHeaderOnlyRequestHash("AuthRefreshToken", "token-2", "127.0.0.1");

        Assert.NotEqual(first, second);
    }

    [Fact]
    public async Task CompleteAndCommitAsync_CommitsUnderlyingTransaction()
    {
        var transaction = new RecordingTransactionScope();
        var idempotencyService = new RecordingIdempotencyService();
        var responseContext = CreateResponseContext();
        responseContext.Response.Headers.Append("Set-Cookie", new StringValues("accessToken=abc; path=/"));

        await using var scope = new SyncIdempotencyExecutionScope(
            new SyncIdempotencyContext("corr-commit"),
            transaction);

        await scope.CompleteAndCommitAsync(
            StatusCodes.Status200OK,
            new { success = true },
            idempotencyService,
            CancellationToken.None,
            responseContext.Response);

        Assert.True(transaction.Committed);
        Assert.False(transaction.RolledBack);
        Assert.NotNull(idempotencyService.CompletedHeaders);
        Assert.True(idempotencyService.CompletedHeaders!.ContainsKey("Set-Cookie"));
    }

    [Fact]
    public async Task RollbackAsync_RollsBackUnderlyingTransaction()
    {
        var transaction = new RecordingTransactionScope();

        await using var scope = new SyncIdempotencyExecutionScope(
            new SyncIdempotencyContext("corr-rollback"),
            transaction);

        await scope.RollbackAsync(CancellationToken.None);

        Assert.False(transaction.Committed);
        Assert.True(transaction.RolledBack);
    }

    [Fact]
    public async Task TryBeginSyncRequest_WhenExistingRequestCompleted_ReplaysStoredResponse()
    {
        var httpContext = new DefaultHttpContext();
        httpContext.Request.Headers["Idempotency-Key"] = "auth-op-1";

        var service = PrecomputedIdempotencyService.ForState(
            IdempotencyStartState.Completed,
            new IdempotencyRecord
            {
                EndpointName = "AuthLogin",
                OperationId = "auth-op-1",
                RequestHash = "req-hash-1",
                CorrelationId = "corr-1",
                FinalHttpStatus = StatusCodes.Status200OK,
                FinalResponseJson = "{\"success\":true}",
                FinalResponseHeadersJson = "{\"Set-Cookie\":[\"accessToken=abc; path=/\"],\"Location\":[\"/api/v1/auth/login\"]}"
            });

        var result = await IdempotencyEndpointHelper.TryBeginSyncRequest(
            httpContext,
            "AuthLogin",
            new { email = "admin@example.com" },
            service,
            new RecordingCurrentUserService(),
            CancellationToken.None,
            requireIdempotencyKey: true,
            requestHash: "req-hash-1");

        Assert.False(result.ShouldProceed);
        Assert.NotNull(result.EarlyReturn);

        var responseContext = await ExecuteResultAsync(result.EarlyReturn!);
        Assert.Equal(StatusCodes.Status200OK, responseContext.Response.StatusCode);
        Assert.Equal("accessToken=abc; path=/", responseContext.Response.Headers["Set-Cookie"].ToString());
        Assert.Equal("/api/v1/auth/login", responseContext.Response.Headers.Location.ToString());

        responseContext.Response.Body.Position = 0;
        using var reader = new StreamReader(responseContext.Response.Body);
        Assert.Equal("{\"success\":true}", await reader.ReadToEndAsync());
    }

    [Fact]
    public async Task TryBeginSyncRequest_WhenExistingRequestIsProcessing_ReturnsConflict()
    {
        var httpContext = new DefaultHttpContext();
        httpContext.Request.Headers["Idempotency-Key"] = "auth-op-2";

        var result = await IdempotencyEndpointHelper.TryBeginSyncRequest(
            httpContext,
            "AuthLogin",
            new { email = "admin@example.com" },
            PrecomputedIdempotencyService.ForState(IdempotencyStartState.Processing),
            new RecordingCurrentUserService(),
            CancellationToken.None,
            requireIdempotencyKey: true,
            requestHash: "req-hash-2");

        Assert.False(result.ShouldProceed);
        Assert.NotNull(result.EarlyReturn);

        var responseContext = await ExecuteResultAsync(result.EarlyReturn!);
        Assert.Equal(StatusCodes.Status409Conflict, responseContext.Response.StatusCode);

        responseContext.Response.Body.Position = 0;
        using var reader = new StreamReader(responseContext.Response.Body);
        var body = await reader.ReadToEndAsync();
        Assert.Contains("already being processed", body, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public async Task TryBeginSyncRequest_WhenExistingRequestFailed_ReturnsUnprocessableEntity()
    {
        var httpContext = new DefaultHttpContext();
        httpContext.Request.Headers["Idempotency-Key"] = "auth-op-3";

        var result = await IdempotencyEndpointHelper.TryBeginSyncRequest(
            httpContext,
            "AuthLogin",
            new { email = "admin@example.com" },
            PrecomputedIdempotencyService.ForState(
                IdempotencyStartState.Failed,
                new IdempotencyRecord
                {
                    EndpointName = "AuthLogin",
                    OperationId = "auth-op-3",
                    RequestHash = "req-hash-3",
                    CorrelationId = "corr-3",
                    ErrorMessage = "Previous attempt failed."
                }),
            new RecordingCurrentUserService(),
            CancellationToken.None,
            requireIdempotencyKey: true,
            requestHash: "req-hash-3");

        Assert.False(result.ShouldProceed);
        Assert.NotNull(result.EarlyReturn);

        var responseContext = await ExecuteResultAsync(result.EarlyReturn!);
        Assert.Equal(StatusCodes.Status422UnprocessableEntity, responseContext.Response.StatusCode);

        responseContext.Response.Body.Position = 0;
        using var reader = new StreamReader(responseContext.Response.Body);
        var body = await reader.ReadToEndAsync();
        Assert.Contains("Previous attempt failed", body, StringComparison.Ordinal);
    }

    [Fact]
    public async Task TryBeginSyncRequest_WhenRequestHashConflicts_ReturnsConflict()
    {
        var httpContext = new DefaultHttpContext();
        httpContext.Request.Headers["Idempotency-Key"] = "auth-op-4";

        var result = await IdempotencyEndpointHelper.TryBeginSyncRequest(
            httpContext,
            "AuthLogin",
            new { email = "admin@example.com" },
            PrecomputedIdempotencyService.ForState(IdempotencyStartState.Conflict),
            new RecordingCurrentUserService(),
            CancellationToken.None,
            requireIdempotencyKey: true,
            requestHash: "req-hash-4");

        Assert.False(result.ShouldProceed);
        Assert.NotNull(result.EarlyReturn);

        var responseContext = await ExecuteResultAsync(result.EarlyReturn!);
        Assert.Equal(StatusCodes.Status409Conflict, responseContext.Response.StatusCode);

        responseContext.Response.Body.Position = 0;
        using var reader = new StreamReader(responseContext.Response.Body);
        var body = await reader.ReadToEndAsync();
        Assert.Contains("different payload", body, StringComparison.OrdinalIgnoreCase);
    }

    private static async Task<DefaultHttpContext> ExecuteResultAsync(IResult result)
    {
        var context = CreateResponseContext();
        await result.ExecuteAsync(context);
        return context;
    }

    private static DefaultHttpContext CreateResponseContext()
    {
        var context = new DefaultHttpContext
        {
            RequestServices = new ServiceCollection()
                .AddLogging()
                .Configure<Microsoft.AspNetCore.Http.Json.JsonOptions>(_ => { })
                .BuildServiceProvider()
        };
        context.Response.Body = new MemoryStream();
        return context;
    }

    private sealed class RecordingIdempotencyService : IIdempotencyService
    {
        public IdempotencyStartRequest? LastRequest { get; private set; }
        public IReadOnlyDictionary<string, string[]>? CompletedHeaders { get; private set; }

        public Task<IdempotencyStartResult> BeginRequestAsync(IdempotencyStartRequest request, CancellationToken cancellationToken = default)
        {
            LastRequest = request;

            var record = new IdempotencyRecord
            {
                EndpointName = request.EndpointName,
                OperationId = request.OperationId,
                RequestHash = request.RequestHash,
                CorrelationId = request.CorrelationId,
                AcceptedHttpStatus = request.AcceptedHttpStatus,
                AcceptedResponseJson = request.AcceptedResponseJson
            };

            return Task.FromResult(new IdempotencyStartResult(IdempotencyStartState.Started, record));
        }

        public Task<IdempotencyRecord?> GetRequestByOperationAsync(string endpointName, string operationId, CancellationToken cancellationToken = default)
            => throw new NotSupportedException();

        public Task<IdempotencyRecord?> GetRequestByCorrelationIdAsync(string correlationId, CancellationToken cancellationToken = default)
            => throw new NotSupportedException();

        public Task MarkCompletedByCorrelationAsync(
            string correlationId,
            int finalHttpStatus,
            object finalResponse,
            CancellationToken cancellationToken = default,
            IReadOnlyDictionary<string, string[]>? finalResponseHeaders = null)
        {
            CompletedHeaders = finalResponseHeaders;
            return Task.CompletedTask;
        }

        public Task MarkFailedByCorrelationAsync(string correlationId, string errorCode, string errorMessage, CancellationToken cancellationToken = default)
            => Task.CompletedTask;

        public Task<ConsumerClaimResult> ClaimConsumerAsync(string consumerName, string operationId, Guid? messageId, string? correlationId, CancellationToken cancellationToken = default)
            => throw new NotSupportedException();

        public Task MarkConsumerCompletedAsync(Guid inboxId, CancellationToken cancellationToken = default)
            => Task.CompletedTask;

        public Task MarkConsumerFailedAsync(Guid inboxId, string error, CancellationToken cancellationToken = default)
            => Task.CompletedTask;
    }

    private sealed class RecordingCurrentUserService : ICurrentUserService
    {
        public Guid? UserId => Guid.Parse("11111111-1111-1111-1111-111111111111");
        public string? UserName => "tester";
        public string? Email => "tester@example.com";
        public string? CorrelationId => "request-correlation";
        public bool IsAuthenticated => true;

        public bool IsInRole(string role) => false;
    }

    private sealed class RecordingTransactionScope : ITransactionScope
    {
        public bool Committed { get; private set; }
        public bool RolledBack { get; private set; }
        public bool Disposed { get; private set; }

        public Task CommitAsync(CancellationToken cancellationToken = default)
        {
            Committed = true;
            return Task.CompletedTask;
        }

        public Task RollbackAsync(CancellationToken cancellationToken = default)
        {
            RolledBack = true;
            return Task.CompletedTask;
        }

        public void Dispose()
        {
            Disposed = true;
        }

        public ValueTask DisposeAsync()
        {
            Disposed = true;
            return ValueTask.CompletedTask;
        }
    }

    private sealed class PrecomputedIdempotencyService : IIdempotencyService
    {
        private readonly IdempotencyStartResult _startResult;

        private PrecomputedIdempotencyService(IdempotencyStartResult startResult)
        {
            _startResult = startResult;
        }

        public static PrecomputedIdempotencyService ForState(
            IdempotencyStartState state,
            IdempotencyRecord? record = null)
        {
            var resolvedRecord = record ?? new IdempotencyRecord
            {
                EndpointName = "AuthLogin",
                OperationId = "precomputed-op",
                RequestHash = "precomputed-hash",
                CorrelationId = "precomputed-correlation"
            };

            return new PrecomputedIdempotencyService(new IdempotencyStartResult(state, resolvedRecord));
        }

        public Task<IdempotencyStartResult> BeginRequestAsync(IdempotencyStartRequest request, CancellationToken cancellationToken = default)
            => Task.FromResult(_startResult);

        public Task<IdempotencyRecord?> GetRequestByOperationAsync(string endpointName, string operationId, CancellationToken cancellationToken = default)
            => throw new NotSupportedException();

        public Task<IdempotencyRecord?> GetRequestByCorrelationIdAsync(string correlationId, CancellationToken cancellationToken = default)
            => throw new NotSupportedException();

        public Task MarkCompletedByCorrelationAsync(
            string correlationId,
            int finalHttpStatus,
            object finalResponse,
            CancellationToken cancellationToken = default,
            IReadOnlyDictionary<string, string[]>? finalResponseHeaders = null)
            => Task.CompletedTask;

        public Task MarkFailedByCorrelationAsync(string correlationId, string errorCode, string errorMessage, CancellationToken cancellationToken = default)
            => Task.CompletedTask;

        public Task<ConsumerClaimResult> ClaimConsumerAsync(string consumerName, string operationId, Guid? messageId, string? correlationId, CancellationToken cancellationToken = default)
            => throw new NotSupportedException();

        public Task MarkConsumerCompletedAsync(Guid inboxId, CancellationToken cancellationToken = default)
            => Task.CompletedTask;

        public Task MarkConsumerFailedAsync(Guid inboxId, string error, CancellationToken cancellationToken = default)
            => Task.CompletedTask;
    }
}

