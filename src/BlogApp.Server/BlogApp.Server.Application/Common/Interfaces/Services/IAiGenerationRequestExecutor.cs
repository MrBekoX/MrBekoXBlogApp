using BlogApp.BuildingBlocks.Messaging.Abstractions;
using BlogApp.Server.Application.Common.Models;

namespace BlogApp.Server.Application.Common.Interfaces.Services;

public interface IAiGenerationRequestExecutor
{
    Task<AiGenerationExecutionResult<TResult>> ExecuteAsync<TEvent, TResult>(
        AiGenerationExecutionRequest<TEvent> request,
        CancellationToken cancellationToken = default)
        where TEvent : IIntegrationEvent;
}
