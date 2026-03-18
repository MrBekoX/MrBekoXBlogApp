using BlogApp.BuildingBlocks.Messaging;
using BlogApp.BuildingBlocks.Messaging.Events.Ai;
using BlogApp.Server.Application.Common.Interfaces.Services;
using BlogApp.Server.Application.Common.Models;
using MediatR;

namespace BlogApp.Server.Application.Features.AiFeature.Commands.GeoOptimizeCommand;

public class GeoOptimizeCommandHandler(
    IAiGenerationRequestExecutor executor) : IRequestHandler<GeoOptimizeCommandRequest, GeoOptimizeCommandResponse>
{
    public async Task<GeoOptimizeCommandResponse> Handle(
        GeoOptimizeCommandRequest request,
        CancellationToken cancellationToken)
    {
        var execution = await executor.ExecuteAsync<AiGeoOptimizeRequestedEvent, GeoOptimizationResult>(
            new AiGenerationExecutionRequest<AiGeoOptimizeRequestedEvent>(
                EndpointName: "ai.geo-optimize",
                OperationId: request.OperationId,
                RequestPayload: request,
                UserId: request.UserId,
                ResourceId: null,
                BuildEvent: (correlationId, operationId, causationId) => new AiGeoOptimizeRequestedEvent
                {
                    OperationId = operationId,
                    CorrelationId = correlationId,
                    CausationId = causationId,
                    Payload = new AiGeoOptimizePayload
                    {
                        Content = request.Content,
                        UserId = request.UserId,
                        TargetRegion = request.TargetRegion,
                        RequestedAt = DateTime.UtcNow,
                        Language = request.Language
                    }
                },
                RoutingKey: MessagingConstants.RoutingKeys.AiGeoOptimizeRequested,
                Timeout: TimeSpan.FromSeconds(120)),
            cancellationToken);

        return new GeoOptimizeCommandResponse
        {
            OperationId = execution.OperationId,
            CorrelationId = execution.CorrelationId,
            IsProcessing = execution.State == AiGenerationExecutionState.Processing,
            ErrorCode = execution.ErrorCode,
            ErrorMessage = execution.ErrorMessage,
            Data = execution.State == AiGenerationExecutionState.Completed
                ? Result.Success(execution.Result!)
                : Result.Failure<GeoOptimizationResult>(execution.ErrorMessage ?? "AI GEO optimization is still processing.")
        };
    }
}

