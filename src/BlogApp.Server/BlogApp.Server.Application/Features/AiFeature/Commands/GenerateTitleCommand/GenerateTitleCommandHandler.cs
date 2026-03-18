using BlogApp.BuildingBlocks.Messaging;
using BlogApp.BuildingBlocks.Messaging.Events.Ai;
using BlogApp.Server.Application.Common.Interfaces.Services;
using BlogApp.Server.Application.Common.Models;
using MediatR;

namespace BlogApp.Server.Application.Features.AiFeature.Commands.GenerateTitleCommand;

public class GenerateTitleCommandHandler(
    IAiGenerationRequestExecutor executor) : IRequestHandler<GenerateTitleCommandRequest, GenerateTitleCommandResponse>
{
    public async Task<GenerateTitleCommandResponse> Handle(
        GenerateTitleCommandRequest request,
        CancellationToken cancellationToken)
    {
        var execution = await executor.ExecuteAsync<AiTitleGenerationRequestedEvent, string>(
            new AiGenerationExecutionRequest<AiTitleGenerationRequestedEvent>(
                EndpointName: "ai.generate-title",
                OperationId: request.OperationId,
                RequestPayload: request,
                UserId: request.UserId,
                ResourceId: null,
                BuildEvent: (correlationId, operationId, causationId) => new AiTitleGenerationRequestedEvent
                {
                    OperationId = operationId,
                    CorrelationId = correlationId,
                    CausationId = causationId,
                    Payload = new AiTitleGenerationPayload
                    {
                        Content = request.Content,
                        UserId = request.UserId,
                        RequestedAt = DateTime.UtcNow
                    }
                },
                RoutingKey: MessagingConstants.RoutingKeys.AiTitleGenerationRequested,
                Timeout: TimeSpan.FromSeconds(120)),
            cancellationToken);

        return new GenerateTitleCommandResponse
        {
            OperationId = execution.OperationId,
            CorrelationId = execution.CorrelationId,
            IsProcessing = execution.State == AiGenerationExecutionState.Processing,
            ErrorCode = execution.ErrorCode,
            ErrorMessage = execution.ErrorMessage,
            Data = execution.State == AiGenerationExecutionState.Completed
                ? Result.Success(execution.Result!)
                : Result.Failure<string>(execution.ErrorMessage ?? "AI title generation is still processing.")
        };
    }
}

