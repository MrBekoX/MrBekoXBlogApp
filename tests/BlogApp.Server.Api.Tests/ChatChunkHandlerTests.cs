using BlogApp.Server.Api.Hubs;
using BlogApp.Server.Api.Messaging;
using BlogApp.Server.Application.Common.Interfaces.Services;
using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Domain.Entities;
using Microsoft.AspNetCore.SignalR;
using Microsoft.Extensions.Logging.Abstractions;

namespace BlogApp.Server.Api.Tests;

public class ChatChunkHandlerTests
{
    [Fact]
    public async Task HandleAsync_WhenFinalChunkIsRedelivered_PublishesChunkAndCompletionOnlyOnce()
    {
        var clientProxy = new RecordingClientProxy();
        var hubContext = new RecordingHubContext(clientProxy);
        var idempotencyService = new RecordingIdempotencyService();
        var handler = new ChatChunkHandler(hubContext, idempotencyService, NullLogger<ChatChunkHandler>.Instance);

        var messageId = Guid.NewGuid();
        var @event = new ChatChunkEvent
        {
            MessageId = messageId,
            OperationId = "chat-op-1",
            CorrelationId = "corr-1",
            Payload = new ChatChunkPayload
            {
                SessionId = "session-1",
                Chunk = "Merhaba",
                Sequence = 7,
                IsFinal = true,
            }
        };

        await handler.HandleAsync(@event);
        await handler.HandleAsync(@event);

        Assert.Equal(2, clientProxy.Sends.Count);
        Assert.Equal("ChatChunkReceived", clientProxy.Sends[0].Method);
        Assert.Equal("ChatMessageCompleted", clientProxy.Sends[1].Method);
        Assert.Single(idempotencyService.CompletedInboxIds);
        Assert.Equal(2, idempotencyService.ClaimedKeys.Count);
        Assert.All(idempotencyService.ClaimedKeys, key => Assert.Equal("backend.chat-chunk-handler:chat-op-1:chunk:7", key));
    }

    private sealed class RecordingIdempotencyService : IIdempotencyService
    {
        private readonly Dictionary<string, ConsumerInboxMessage> _records = new();

        public List<Guid> CompletedInboxIds { get; } = new();
        public List<string> ClaimedKeys { get; } = new();

        public Task<IdempotencyStartResult> BeginRequestAsync(IdempotencyStartRequest request, CancellationToken cancellationToken = default)
            => throw new NotSupportedException();

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
        {
            var key = $"{consumerName}:{operationId}";
            ClaimedKeys.Add(key);

            if (_records.TryGetValue(key, out var existing))
            {
                var duplicateState = existing.ProcessedAt.HasValue
                    ? ConsumerClaimState.DuplicateCompleted
                    : ConsumerClaimState.DuplicateProcessing;
                return Task.FromResult(new ConsumerClaimResult(duplicateState, existing));
            }

            var record = new ConsumerInboxMessage
            {
                Id = Guid.NewGuid(),
                ConsumerName = consumerName,
                OperationId = operationId,
                MessageId = messageId,
                CorrelationId = correlationId,
            };

            _records[key] = record;
            return Task.FromResult(new ConsumerClaimResult(ConsumerClaimState.Claimed, record));
        }

        public Task MarkConsumerCompletedAsync(Guid inboxId, CancellationToken cancellationToken = default)
        {
            CompletedInboxIds.Add(inboxId);
            var record = _records.Values.Single(item => item.Id == inboxId);
            record.ProcessedAt = DateTime.UtcNow;
            return Task.CompletedTask;
        }

        public Task MarkConsumerFailedAsync(Guid inboxId, string error, CancellationToken cancellationToken = default)
            => Task.CompletedTask;
    }

    private sealed class RecordingHubContext : IHubContext<ChatEventsHub>
    {
        public RecordingHubContext(RecordingClientProxy proxy)
        {
            Clients = new RecordingHubClients(proxy);
            Groups = new RecordingGroupManager();
        }

        public IHubClients Clients { get; }
        public IGroupManager Groups { get; }
    }

    private sealed class RecordingHubClients : IHubClients
    {
        private readonly IClientProxy _proxy;

        public RecordingHubClients(IClientProxy proxy)
        {
            _proxy = proxy;
        }

        public IClientProxy All => _proxy;
        public IClientProxy AllExcept(IReadOnlyList<string> excludedConnectionIds) => _proxy;
        public IClientProxy Client(string connectionId) => _proxy;
        public IClientProxy Clients(IReadOnlyList<string> connectionIds) => _proxy;
        public IClientProxy Group(string groupName) => _proxy;
        public IClientProxy GroupExcept(string groupName, IReadOnlyList<string> excludedConnectionIds) => _proxy;
        public IClientProxy Groups(IReadOnlyList<string> groupNames) => _proxy;
        public IClientProxy User(string userId) => _proxy;
        public IClientProxy Users(IReadOnlyList<string> userIds) => _proxy;
    }

    private sealed class RecordingGroupManager : IGroupManager
    {
        public Task AddToGroupAsync(string connectionId, string groupName, CancellationToken cancellationToken = default)
            => Task.CompletedTask;

        public Task RemoveFromGroupAsync(string connectionId, string groupName, CancellationToken cancellationToken = default)
            => Task.CompletedTask;
    }

    private sealed class RecordingClientProxy : IClientProxy
    {
        public List<(string Method, IReadOnlyList<object?> Args)> Sends { get; } = new();

        public Task SendCoreAsync(string method, object?[] args, CancellationToken cancellationToken = default)
        {
            Sends.Add((method, args));
            return Task.CompletedTask;
        }
    }
}
