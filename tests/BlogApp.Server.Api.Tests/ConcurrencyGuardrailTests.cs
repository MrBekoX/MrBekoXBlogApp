using BlogApp.BuildingBlocks.Messaging.Abstractions;
using BlogApp.Server.Application.Common.Constants;
using BlogApp.Server.Application.Common.Interfaces.Services;
using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Domain.Entities;
using BlogApp.Server.Infrastructure.Persistence;
using BlogApp.Server.Infrastructure.Services;
using Microsoft.AspNetCore.Http;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata;
using Microsoft.Extensions.Logging.Abstractions;

namespace BlogApp.Server.Api.Tests;

public class ConcurrencyGuardrailTests
{
    [Fact]
    public async Task DispatchAsync_WhenOutboxDisabled_FailsFastWithoutStartingIdempotency()
    {
        await using var context = CreateDbContext();
        var dispatcher = new AsyncOperationDispatcher(
            context,
            new ThrowingIdempotencyService(),
            new NoOpOutboxService(NullLogger<NoOpOutboxService>.Instance),
            new StubCurrentUserService());

        var result = await dispatcher.DispatchAsync(
            new AsyncOperationDispatchRequest<TestIntegrationEvent>(
                EndpointName: "chat.message",
                OperationId: "op-1",
                RequestPayload: new { value = "payload" },
                UserId: null,
                SessionId: "session-1",
                ResourceId: "resource-1",
                BuildEvent: static (correlationId, operationId, causationId) => new TestIntegrationEvent
                {
                    OperationId = operationId,
                    CorrelationId = correlationId,
                    CausationId = causationId
                },
                RoutingKey: "routing.key",
                AcceptedStatusCode: StatusCodes.Status202Accepted,
                BuildAcceptedResponse: static (operationId, correlationId) => new { operationId, correlationId }),
            CancellationToken.None);

        Assert.Equal(AsyncOperationDispatchState.Failed, result.State);
        Assert.Equal(AsyncOperationErrorCodes.AsyncDispatchUnavailable, result.ErrorCode);
        Assert.Equal(StatusCodes.Status503ServiceUnavailable, result.Response.StatusCode);
    }

    [Fact]
    public async Task ExecuteAsync_WhenOutboxDisabled_FailsFastWithoutStartingIdempotency()
    {
        await using var context = CreateDbContext();
        var executor = new AiGenerationRequestExecutor(
            context,
            new ThrowingIdempotencyService(),
            new NoOpOutboxService(NullLogger<NoOpOutboxService>.Instance),
            new StubCurrentUserService());

        var result = await executor.ExecuteAsync<TestIntegrationEvent, string>(
            new AiGenerationExecutionRequest<TestIntegrationEvent>(
                EndpointName: "ai.generate-title",
                OperationId: "op-2",
                RequestPayload: new { content = "hello" },
                UserId: Guid.NewGuid(),
                ResourceId: null,
                BuildEvent: static (correlationId, operationId, causationId) => new TestIntegrationEvent
                {
                    OperationId = operationId,
                    CorrelationId = correlationId,
                    CausationId = causationId
                },
                RoutingKey: "routing.key",
                Timeout: TimeSpan.FromSeconds(30)),
            CancellationToken.None);

        Assert.Equal(AiGenerationExecutionState.Failed, result.State);
        Assert.Equal(AsyncOperationErrorCodes.AsyncDispatchUnavailable, result.ErrorCode);
    }

    [Fact]
    public void BlogPostModel_MapsVersionToPostgresXminConcurrencyToken()
    {
        using var context = CreateDbContext();
        var entityType = context.Model.FindEntityType(typeof(BlogPost));
        Assert.NotNull(entityType);

        var versionProperty = entityType!.FindProperty(nameof(BlogPost.Version));
        Assert.NotNull(versionProperty);
        Assert.True(versionProperty!.IsConcurrencyToken);
        Assert.Equal(ValueGenerated.OnAddOrUpdate, versionProperty.ValueGenerated);
        Assert.Equal("xmin", versionProperty.GetColumnName(StoreObjectIdentifier.Table("posts", null)));
    }

    private static AppDbContext CreateDbContext()
    {
        var options = new DbContextOptionsBuilder<AppDbContext>()
            .UseNpgsql("Host=localhost;Database=blogapp_tests;Username=postgres;Password=postgres")
            .Options;

        return new AppDbContext(options);
    }

    private sealed class ThrowingIdempotencyService : IIdempotencyService
    {
        public Task<IdempotencyStartResult> BeginRequestAsync(IdempotencyStartRequest request, CancellationToken cancellationToken = default)
            => throw new Xunit.Sdk.XunitException("Idempotency service should not be called when outbox is disabled.");

        public Task<IdempotencyRecord?> GetRequestByOperationAsync(string endpointName, string operationId, CancellationToken cancellationToken = default)
            => throw new NotSupportedException();

        public Task<IdempotencyRecord?> GetRequestByCorrelationIdAsync(string correlationId, CancellationToken cancellationToken = default)
            => throw new NotSupportedException();

        public Task MarkCompletedByCorrelationAsync(string correlationId, int finalHttpStatus, object finalResponse, CancellationToken cancellationToken = default, IReadOnlyDictionary<string, string[]>? finalResponseHeaders = null)
            => throw new NotSupportedException();

        public Task MarkFailedByCorrelationAsync(string correlationId, string errorCode, string errorMessage, CancellationToken cancellationToken = default)
            => throw new NotSupportedException();

        public Task<ConsumerClaimResult> ClaimConsumerAsync(string consumerName, string operationId, Guid? messageId, string? correlationId, CancellationToken cancellationToken = default)
            => throw new NotSupportedException();

        public Task MarkConsumerCompletedAsync(Guid inboxId, CancellationToken cancellationToken = default)
            => throw new NotSupportedException();

        public Task MarkConsumerFailedAsync(Guid inboxId, string error, CancellationToken cancellationToken = default)
            => throw new NotSupportedException();
    }

    private sealed class StubCurrentUserService : ICurrentUserService
    {
        public Guid? UserId => Guid.Parse("11111111-1111-1111-1111-111111111111");
        public string? UserName => "guardrail-tester";
        public string? Email => "guardrail@example.com";
        public string? CorrelationId => "corr-guardrail";
        public bool IsAuthenticated => true;

        public bool IsInRole(string role) => false;
    }

    private sealed class TestIntegrationEvent : IIntegrationEvent
    {
        public Guid MessageId { get; init; } = Guid.NewGuid();
        public string? OperationId { get; init; }
        public string? CorrelationId { get; init; }
        public string? CausationId { get; init; }
        public DateTime Timestamp { get; init; } = DateTime.UtcNow;
        public string EventType => "TestIntegrationEvent";
    }
}
