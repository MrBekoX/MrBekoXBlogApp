using BlogApp.BuildingBlocks.Messaging;
using BlogApp.BuildingBlocks.Messaging.Events.Ai;
using BlogApp.Server.Application.Common.Interfaces.Services;
using BlogApp.Server.Application.Common.Models;
using MediatR;

namespace BlogApp.Server.Application.Features.AiFeature.Commands.GenerateTagsCommand;

public class GenerateTagsCommandHandler(
    IAiGenerationRequestExecutor executor) : IRequestHandler<GenerateTagsCommandRequest, GenerateTagsCommandResponse>
{
    public async Task<GenerateTagsCommandResponse> Handle(
        GenerateTagsCommandRequest request,
        CancellationToken cancellationToken)
    {
        var execution = await executor.ExecuteAsync<AiTagsGenerationRequestedEvent, string[]>(
            new AiGenerationExecutionRequest<AiTagsGenerationRequestedEvent>(
                EndpointName: "ai.generate-tags",
                OperationId: request.OperationId,
                RequestPayload: request,
                UserId: request.UserId,
                ResourceId: null,
                BuildEvent: (correlationId, operationId, causationId) => new AiTagsGenerationRequestedEvent
                {
                    OperationId = operationId,
                    CorrelationId = correlationId,
                    CausationId = causationId,
                    Payload = new AiTagsGenerationPayload
                    {
                        Content = request.Content,
                        UserId = request.UserId,
                        RequestedAt = DateTime.UtcNow
                    }
                },
                RoutingKey: MessagingConstants.RoutingKeys.AiTagsGenerationRequested,
                Timeout: TimeSpan.FromSeconds(120)),
            cancellationToken);

        return new GenerateTagsCommandResponse
        {
            OperationId = execution.OperationId,
            CorrelationId = execution.CorrelationId,
            IsProcessing = execution.State == AiGenerationExecutionState.Processing,
            ErrorCode = execution.ErrorCode,
            ErrorMessage = execution.ErrorMessage,
            Data = execution.State == AiGenerationExecutionState.Completed
                ? Result.Success(execution.Result!)
                : Result.Failure<string[]>(execution.ErrorMessage ?? "AI tags generation is still processing.")
        };
    }
}

