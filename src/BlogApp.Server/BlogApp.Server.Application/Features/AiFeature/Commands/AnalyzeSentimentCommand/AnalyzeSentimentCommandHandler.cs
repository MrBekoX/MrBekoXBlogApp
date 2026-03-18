using BlogApp.BuildingBlocks.Messaging;
using BlogApp.BuildingBlocks.Messaging.Events.Ai;
using BlogApp.Server.Application.Common.Interfaces.Services;
using BlogApp.Server.Application.Common.Models;
using MediatR;

namespace BlogApp.Server.Application.Features.AiFeature.Commands.AnalyzeSentimentCommand;

public class AnalyzeSentimentCommandHandler(
    IAiGenerationRequestExecutor executor) : IRequestHandler<AnalyzeSentimentCommandRequest, AnalyzeSentimentCommandResponse>
{
    public async Task<AnalyzeSentimentCommandResponse> Handle(
        AnalyzeSentimentCommandRequest request,
        CancellationToken cancellationToken)
    {
        var execution = await executor.ExecuteAsync<AiSentimentRequestedEvent, SentimentResult>(
            new AiGenerationExecutionRequest<AiSentimentRequestedEvent>(
                EndpointName: "ai.sentiment",
                OperationId: request.OperationId,
                RequestPayload: request,
                UserId: request.UserId,
                ResourceId: null,
                BuildEvent: (correlationId, operationId, causationId) => new AiSentimentRequestedEvent
                {
                    OperationId = operationId,
                    CorrelationId = correlationId,
                    CausationId = causationId,
                    Payload = new AiSentimentPayload
                    {
                        Content = request.Content,
                        UserId = request.UserId,
                        RequestedAt = DateTime.UtcNow,
                        Language = request.Language
                    }
                },
                RoutingKey: MessagingConstants.RoutingKeys.AiSentimentRequested,
                Timeout: TimeSpan.FromSeconds(120)),
            cancellationToken);

        return new AnalyzeSentimentCommandResponse
        {
            OperationId = execution.OperationId,
            CorrelationId = execution.CorrelationId,
            IsProcessing = execution.State == AiGenerationExecutionState.Processing,
            ErrorCode = execution.ErrorCode,
            ErrorMessage = execution.ErrorMessage,
            Data = execution.State == AiGenerationExecutionState.Completed
                ? Result.Success(execution.Result!)
                : Result.Failure<SentimentResult>(execution.ErrorMessage ?? "AI sentiment analysis is still processing.")
        };
    }
}

