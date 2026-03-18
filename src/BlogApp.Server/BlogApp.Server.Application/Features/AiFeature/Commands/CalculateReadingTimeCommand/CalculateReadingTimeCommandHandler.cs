using BlogApp.BuildingBlocks.Messaging;
using BlogApp.BuildingBlocks.Messaging.Events.Ai;
using BlogApp.Server.Application.Common.Interfaces.Services;
using BlogApp.Server.Application.Common.Models;
using MediatR;

namespace BlogApp.Server.Application.Features.AiFeature.Commands.CalculateReadingTimeCommand;

public class CalculateReadingTimeCommandHandler(
    IAiGenerationRequestExecutor executor) : IRequestHandler<CalculateReadingTimeCommandRequest, CalculateReadingTimeCommandResponse>
{
    public async Task<CalculateReadingTimeCommandResponse> Handle(
        CalculateReadingTimeCommandRequest request,
        CancellationToken cancellationToken)
    {
        var execution = await executor.ExecuteAsync<AiReadingTimeRequestedEvent, ReadingTimeResult>(
            new AiGenerationExecutionRequest<AiReadingTimeRequestedEvent>(
                EndpointName: "ai.reading-time",
                OperationId: request.OperationId,
                RequestPayload: request,
                UserId: request.UserId,
                ResourceId: null,
                BuildEvent: (correlationId, operationId, causationId) => new AiReadingTimeRequestedEvent
                {
                    OperationId = operationId,
                    CorrelationId = correlationId,
                    CausationId = causationId,
                    Payload = new AiReadingTimePayload
                    {
                        Content = request.Content,
                        UserId = request.UserId,
                        RequestedAt = DateTime.UtcNow
                    }
                },
                RoutingKey: MessagingConstants.RoutingKeys.AiReadingTimeRequested,
                Timeout: TimeSpan.FromSeconds(60)),
            cancellationToken);

        return new CalculateReadingTimeCommandResponse
        {
            OperationId = execution.OperationId,
            CorrelationId = execution.CorrelationId,
            IsProcessing = execution.State == AiGenerationExecutionState.Processing,
            ErrorCode = execution.ErrorCode,
            ErrorMessage = execution.ErrorMessage,
            Data = execution.State == AiGenerationExecutionState.Completed
                ? Result.Success(execution.Result!)
                : Result.Failure<ReadingTimeResult>(execution.ErrorMessage ?? "AI reading time calculation is still processing.")
        };
    }
}

