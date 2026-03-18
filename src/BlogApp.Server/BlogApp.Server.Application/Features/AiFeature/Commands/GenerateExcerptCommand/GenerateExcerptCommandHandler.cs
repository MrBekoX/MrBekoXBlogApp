using BlogApp.BuildingBlocks.Messaging;
using BlogApp.BuildingBlocks.Messaging.Events.Ai;
using BlogApp.Server.Application.Common.Interfaces.Services;
using BlogApp.Server.Application.Common.Models;
using MediatR;

namespace BlogApp.Server.Application.Features.AiFeature.Commands.GenerateExcerptCommand;

public class GenerateExcerptCommandHandler(
    IAiGenerationRequestExecutor executor) : IRequestHandler<GenerateExcerptCommandRequest, GenerateExcerptCommandResponse>
{
    public async Task<GenerateExcerptCommandResponse> Handle(
        GenerateExcerptCommandRequest request,
        CancellationToken cancellationToken)
    {
        var execution = await executor.ExecuteAsync<AiExcerptGenerationRequestedEvent, string>(
            new AiGenerationExecutionRequest<AiExcerptGenerationRequestedEvent>(
                EndpointName: "ai.generate-excerpt",
                OperationId: request.OperationId,
                RequestPayload: request,
                UserId: request.UserId,
                ResourceId: null,
                BuildEvent: (correlationId, operationId, causationId) => new AiExcerptGenerationRequestedEvent
                {
                    OperationId = operationId,
                    CorrelationId = correlationId,
                    CausationId = causationId,
                    Payload = new AiExcerptGenerationPayload
                    {
                        Content = request.Content,
                        UserId = request.UserId,
                        RequestedAt = DateTime.UtcNow
                    }
                },
                RoutingKey: MessagingConstants.RoutingKeys.AiExcerptGenerationRequested,
                Timeout: TimeSpan.FromSeconds(120)),
            cancellationToken);

        return new GenerateExcerptCommandResponse
        {
            OperationId = execution.OperationId,
            CorrelationId = execution.CorrelationId,
            IsProcessing = execution.State == AiGenerationExecutionState.Processing,
            ErrorCode = execution.ErrorCode,
            ErrorMessage = execution.ErrorMessage,
            Data = execution.State == AiGenerationExecutionState.Completed
                ? Result.Success(execution.Result!)
                : Result.Failure<string>(execution.ErrorMessage ?? "AI excerpt generation is still processing.")
        };
    }
}

