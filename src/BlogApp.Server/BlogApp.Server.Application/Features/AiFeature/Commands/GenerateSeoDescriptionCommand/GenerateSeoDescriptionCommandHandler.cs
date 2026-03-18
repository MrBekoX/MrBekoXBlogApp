using BlogApp.BuildingBlocks.Messaging;
using BlogApp.BuildingBlocks.Messaging.Events.Ai;
using BlogApp.Server.Application.Common.Interfaces.Services;
using BlogApp.Server.Application.Common.Models;
using MediatR;

namespace BlogApp.Server.Application.Features.AiFeature.Commands.GenerateSeoDescriptionCommand;

public class GenerateSeoDescriptionCommandHandler(
    IAiGenerationRequestExecutor executor) : IRequestHandler<GenerateSeoDescriptionCommandRequest, GenerateSeoDescriptionCommandResponse>
{
    public async Task<GenerateSeoDescriptionCommandResponse> Handle(
        GenerateSeoDescriptionCommandRequest request,
        CancellationToken cancellationToken)
    {
        var execution = await executor.ExecuteAsync<AiSeoDescriptionGenerationRequestedEvent, string>(
            new AiGenerationExecutionRequest<AiSeoDescriptionGenerationRequestedEvent>(
                EndpointName: "ai.generate-seo",
                OperationId: request.OperationId,
                RequestPayload: request,
                UserId: request.UserId,
                ResourceId: null,
                BuildEvent: (correlationId, operationId, causationId) => new AiSeoDescriptionGenerationRequestedEvent
                {
                    OperationId = operationId,
                    CorrelationId = correlationId,
                    CausationId = causationId,
                    Payload = new AiSeoDescriptionGenerationPayload
                    {
                        Content = request.Content,
                        UserId = request.UserId,
                        RequestedAt = DateTime.UtcNow
                    }
                },
                RoutingKey: MessagingConstants.RoutingKeys.AiSeoGenerationRequested,
                Timeout: TimeSpan.FromSeconds(120)),
            cancellationToken);

        return new GenerateSeoDescriptionCommandResponse
        {
            OperationId = execution.OperationId,
            CorrelationId = execution.CorrelationId,
            IsProcessing = execution.State == AiGenerationExecutionState.Processing,
            ErrorCode = execution.ErrorCode,
            ErrorMessage = execution.ErrorMessage,
            Data = execution.State == AiGenerationExecutionState.Completed
                ? Result.Success(execution.Result!)
                : Result.Failure<string>(execution.ErrorMessage ?? "AI SEO generation is still processing.")
        };
    }
}

