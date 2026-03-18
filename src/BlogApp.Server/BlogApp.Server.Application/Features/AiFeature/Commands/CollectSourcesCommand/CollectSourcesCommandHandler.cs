using BlogApp.BuildingBlocks.Messaging;
using BlogApp.BuildingBlocks.Messaging.Events.Ai;
using BlogApp.Server.Application.Common.Interfaces.Services;
using BlogApp.Server.Application.Common.Models;
using MediatR;

namespace BlogApp.Server.Application.Features.AiFeature.Commands.CollectSourcesCommand;

public class CollectSourcesCommandHandler(
    IAiGenerationRequestExecutor executor) : IRequestHandler<CollectSourcesCommandRequest, CollectSourcesCommandResponse>
{
    public async Task<CollectSourcesCommandResponse> Handle(
        CollectSourcesCommandRequest request,
        CancellationToken cancellationToken)
    {
        var execution = await executor.ExecuteAsync<AiCollectSourcesRequestedEvent, WebSourceResult[]>(
            new AiGenerationExecutionRequest<AiCollectSourcesRequestedEvent>(
                EndpointName: "ai.collect-sources",
                OperationId: request.OperationId,
                RequestPayload: request,
                UserId: request.UserId,
                ResourceId: null,
                BuildEvent: (correlationId, operationId, causationId) => new AiCollectSourcesRequestedEvent
                {
                    OperationId = operationId,
                    CorrelationId = correlationId,
                    CausationId = causationId,
                    Payload = new AiCollectSourcesPayload
                    {
                        Query = request.Query,
                        UserId = request.UserId,
                        MaxSources = request.MaxSources,
                        RequestedAt = DateTime.UtcNow,
                        Language = request.Language
                    }
                },
                RoutingKey: MessagingConstants.RoutingKeys.AiCollectSourcesRequested,
                Timeout: TimeSpan.FromSeconds(120)),
            cancellationToken);

        return new CollectSourcesCommandResponse
        {
            OperationId = execution.OperationId,
            CorrelationId = execution.CorrelationId,
            IsProcessing = execution.State == AiGenerationExecutionState.Processing,
            ErrorCode = execution.ErrorCode,
            ErrorMessage = execution.ErrorMessage,
            Data = execution.State == AiGenerationExecutionState.Completed
                ? Result.Success(execution.Result!)
                : Result.Failure<WebSourceResult[]>(execution.ErrorMessage ?? "AI source collection is still processing.")
        };
    }
}

