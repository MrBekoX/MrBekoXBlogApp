using BlogApp.BuildingBlocks.Messaging;
using BlogApp.BuildingBlocks.Messaging.Events.Ai;
using BlogApp.Server.Application.Common.Interfaces.Services;
using BlogApp.Server.Application.Common.Models;
using MediatR;

namespace BlogApp.Server.Application.Features.AiFeature.Commands.ExtractKeywordsCommand;

public class ExtractKeywordsCommandHandler(
    IAiGenerationRequestExecutor executor) : IRequestHandler<ExtractKeywordsCommandRequest, ExtractKeywordsCommandResponse>
{
    public async Task<ExtractKeywordsCommandResponse> Handle(
        ExtractKeywordsCommandRequest request,
        CancellationToken cancellationToken)
    {
        var execution = await executor.ExecuteAsync<AiKeywordsRequestedEvent, string[]>(
            new AiGenerationExecutionRequest<AiKeywordsRequestedEvent>(
                EndpointName: "ai.keywords",
                OperationId: request.OperationId,
                RequestPayload: request,
                UserId: request.UserId,
                ResourceId: null,
                BuildEvent: (correlationId, operationId, causationId) => new AiKeywordsRequestedEvent
                {
                    OperationId = operationId,
                    CorrelationId = correlationId,
                    CausationId = causationId,
                    Payload = new AiKeywordsPayload
                    {
                        Content = request.Content,
                        UserId = request.UserId,
                        MaxKeywords = request.MaxKeywords,
                        RequestedAt = DateTime.UtcNow,
                        Language = request.Language
                    }
                },
                RoutingKey: MessagingConstants.RoutingKeys.AiKeywordsRequested,
                Timeout: TimeSpan.FromSeconds(120)),
            cancellationToken);

        return new ExtractKeywordsCommandResponse
        {
            OperationId = execution.OperationId,
            CorrelationId = execution.CorrelationId,
            IsProcessing = execution.State == AiGenerationExecutionState.Processing,
            ErrorCode = execution.ErrorCode,
            ErrorMessage = execution.ErrorMessage,
            Data = execution.State == AiGenerationExecutionState.Completed
                ? Result.Success(execution.Result!)
                : Result.Failure<string[]>(execution.ErrorMessage ?? "AI keywords extraction is still processing.")
        };
    }
}

