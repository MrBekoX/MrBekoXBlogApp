using BlogApp.BuildingBlocks.Messaging;
using BlogApp.BuildingBlocks.Messaging.Events.Ai;
using BlogApp.Server.Application.Common.Interfaces.Persistence;
using BlogApp.Server.Application.Common.Interfaces.Services;
using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.Features.PostFeature.Constants;
using MediatR;

namespace BlogApp.Server.Application.Features.PostFeature.Commands.GenerateAiSummaryCommand;

public class GenerateAiSummaryCommandHandler(
    IUnitOfWork unitOfWork,
    IAiGenerationRequestExecutor executor) : IRequestHandler<GenerateAiSummaryCommandRequest, GenerateAiSummaryCommandResponse>
{
    public async Task<GenerateAiSummaryCommandResponse> Handle(
        GenerateAiSummaryCommandRequest request,
        CancellationToken cancellationToken)
    {
        var post = await unitOfWork.PostsRead.GetByIdAsync(request.PostId, cancellationToken);
        if (post is null)
        {
            return new GenerateAiSummaryCommandResponse
            {
                OperationId = request.OperationId,
                Result = Result.Failure(PostBusinessRuleMessages.PostNotFoundGeneric),
                ErrorCode = "post_not_found",
                ErrorMessage = PostBusinessRuleMessages.PostNotFoundGeneric
            };
        }

        var execution = await executor.ExecuteAsync<AiSummarizeRequestedEvent, string>(
            new AiGenerationExecutionRequest<AiSummarizeRequestedEvent>(
                EndpointName: "posts.generate-ai-summary",
                OperationId: request.OperationId,
                RequestPayload: new
                {
                    request.PostId,
                    request.MaxSentences,
                    request.Language
                },
                UserId: post.AuthorId,
                ResourceId: request.PostId.ToString(),
                BuildEvent: (correlationId, operationId, causationId) => new AiSummarizeRequestedEvent
                {
                    OperationId = operationId,
                    CorrelationId = correlationId,
                    CausationId = causationId,
                    Payload = new AiSummarizePayload
                    {
                        Content = post.Content,
                        UserId = post.AuthorId,
                        MaxSentences = request.MaxSentences,
                        RequestedAt = DateTime.UtcNow,
                        Language = request.Language
                    }
                },
                RoutingKey: MessagingConstants.RoutingKeys.AiSummarizeRequested,
                Timeout: TimeSpan.FromSeconds(120)),
            cancellationToken);

        return new GenerateAiSummaryCommandResponse
        {
            OperationId = execution.OperationId,
            CorrelationId = execution.CorrelationId,
            IsProcessing = execution.State == AiGenerationExecutionState.Processing,
            ErrorCode = execution.ErrorCode,
            ErrorMessage = execution.ErrorMessage,
            Result = execution.State == AiGenerationExecutionState.Completed
                ? Result.Success()
                : execution.State == AiGenerationExecutionState.Conflict
                    ? Result.Failure(execution.ErrorMessage ?? "The same operationId was used with a different payload.")
                    : Result.Failure(execution.ErrorMessage ?? "AI summary generation is still processing."),
            Summary = execution.State == AiGenerationExecutionState.Completed ? execution.Result : null,
            WordCount = post.Content.Split(' ', StringSplitOptions.RemoveEmptyEntries).Length,
            Message = execution.State == AiGenerationExecutionState.Completed
                ? "AI summary generated successfully."
                : execution.State == AiGenerationExecutionState.Processing
                    ? "AI summary request is still processing."
                    : execution.ErrorMessage
        };
    }
}

