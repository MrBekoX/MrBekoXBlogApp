using BlogApp.BuildingBlocks.Messaging;
using BlogApp.BuildingBlocks.Messaging.Events.Ai;
using BlogApp.Server.Application.Common.Interfaces.Services;
using BlogApp.Server.Application.Common.Models;
using MediatR;

namespace BlogApp.Server.Application.Features.AiFeature.Commands.ImproveContentCommand;

public class ImproveContentCommandHandler(
    IAiGenerationRequestExecutor executor) : IRequestHandler<ImproveContentCommandRequest, ImproveContentCommandResponse>
{
    public async Task<ImproveContentCommandResponse> Handle(
        ImproveContentCommandRequest request,
        CancellationToken cancellationToken)
    {
        var execution = await executor.ExecuteAsync<AiContentImprovementRequestedEvent, string>(
            new AiGenerationExecutionRequest<AiContentImprovementRequestedEvent>(
                EndpointName: "ai.improve-content",
                OperationId: request.OperationId,
                RequestPayload: request,
                UserId: request.UserId,
                ResourceId: null,
                BuildEvent: (correlationId, operationId, causationId) => new AiContentImprovementRequestedEvent
                {
                    OperationId = operationId,
                    CorrelationId = correlationId,
                    CausationId = causationId,
                    Payload = new AiContentImprovementPayload
                    {
                        Content = request.Content,
                        UserId = request.UserId,
                        RequestedAt = DateTime.UtcNow
                    }
                },
                RoutingKey: MessagingConstants.RoutingKeys.AiContentImprovementRequested,
                Timeout: TimeSpan.FromSeconds(120)),
            cancellationToken);

        return new ImproveContentCommandResponse
        {
            OperationId = execution.OperationId,
            CorrelationId = execution.CorrelationId,
            IsProcessing = execution.State == AiGenerationExecutionState.Processing,
            ErrorCode = execution.ErrorCode,
            ErrorMessage = execution.ErrorMessage,
            Data = execution.State == AiGenerationExecutionState.Completed
                ? Result.Success(execution.Result!)
                : Result.Failure<string>(execution.ErrorMessage ?? "AI content improvement is still processing.")
        };
    }
}

