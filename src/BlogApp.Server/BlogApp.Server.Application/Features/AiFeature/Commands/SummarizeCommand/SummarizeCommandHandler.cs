using BlogApp.BuildingBlocks.Messaging;
using BlogApp.BuildingBlocks.Messaging.Events.Ai;
using BlogApp.Server.Application.Common.Interfaces.Services;
using BlogApp.Server.Application.Common.Models;
using MediatR;

namespace BlogApp.Server.Application.Features.AiFeature.Commands.SummarizeCommand;

public class SummarizeCommandHandler(
    IAiGenerationRequestExecutor executor) : IRequestHandler<SummarizeCommandRequest, SummarizeCommandResponse>
{
    public async Task<SummarizeCommandResponse> Handle(
        SummarizeCommandRequest request,
        CancellationToken cancellationToken)
    {
        var execution = await executor.ExecuteAsync<AiSummarizeRequestedEvent, string>(
            new AiGenerationExecutionRequest<AiSummarizeRequestedEvent>(
                EndpointName: "ai.summarize",
                OperationId: request.OperationId,
                RequestPayload: request,
                UserId: request.UserId,
                ResourceId: null,
                BuildEvent: (correlationId, operationId, causationId) => new AiSummarizeRequestedEvent
                {
                    OperationId = operationId,
                    CorrelationId = correlationId,
                    CausationId = causationId,
                    Payload = new AiSummarizePayload
                    {
                        Content = request.Content,
                        UserId = request.UserId,
                        MaxSentences = request.MaxSentences,
                        RequestedAt = DateTime.UtcNow,
                        Language = request.Language
                    }
                },
                RoutingKey: MessagingConstants.RoutingKeys.AiSummarizeRequested,
                Timeout: TimeSpan.FromSeconds(120)),
            cancellationToken);

        return new SummarizeCommandResponse
        {
            OperationId = execution.OperationId,
            CorrelationId = execution.CorrelationId,
            IsProcessing = execution.State == AiGenerationExecutionState.Processing,
            ErrorCode = execution.ErrorCode,
            ErrorMessage = execution.ErrorMessage,
            Data = execution.State == AiGenerationExecutionState.Completed
                ? Result.Success(execution.Result!)
                : Result.Failure<string>(execution.ErrorMessage ?? "AI summarization is still processing.")
        };
    }
}

