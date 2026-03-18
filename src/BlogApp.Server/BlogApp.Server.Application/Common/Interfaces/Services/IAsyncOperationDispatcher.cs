using BlogApp.BuildingBlocks.Messaging.Abstractions;
using BlogApp.Server.Application.Common.Models;

namespace BlogApp.Server.Application.Common.Interfaces.Services;

public interface IAsyncOperationDispatcher
{
    Task<AsyncOperationDispatchResult> DispatchAsync<TEvent>(
        AsyncOperationDispatchRequest<TEvent> request,
        CancellationToken cancellationToken = default)
        where TEvent : IIntegrationEvent;
}
