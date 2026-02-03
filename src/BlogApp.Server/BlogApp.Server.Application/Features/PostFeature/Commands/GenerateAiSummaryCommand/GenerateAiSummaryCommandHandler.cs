using BlogApp.BuildingBlocks.Messaging;
using BlogApp.BuildingBlocks.Messaging.Abstractions;
using BlogApp.Server.Application.Common.Events;
using BlogApp.Server.Application.Common.Interfaces.Persistence;
using BlogApp.Server.Application.Common.Interfaces.Services;
using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.Features.PostFeature.Constants;
using MediatR;

namespace BlogApp.Server.Application.Features.PostFeature.Commands.GenerateAiSummaryCommand;

/// <summary>
/// Handler for generating AI summary using RabbitMQ event-driven architecture.
/// Publishes analysis request to AI Agent via RabbitMQ.
/// Results are delivered via SignalR when AI Agent completes.
/// </summary>
public class GenerateAiSummaryCommandHandler(
    IUnitOfWork unitOfWork,
    IEventBus eventBus) : IRequestHandler<GenerateAiSummaryCommandRequest, GenerateAiSummaryCommandResponse>
{
    public async Task<GenerateAiSummaryCommandResponse> Handle(
        GenerateAiSummaryCommandRequest request,
        CancellationToken cancellationToken)
    {
        // 1. Get post
        var post = await unitOfWork.PostsRead.GetByIdAsync(request.PostId, cancellationToken);
        if (post is null)
        {
            return new GenerateAiSummaryCommandResponse
            {
                Result = Result.Failure(PostBusinessRuleMessages.PostNotFoundGeneric)
            };
        }

        // 2. Generate correlation ID for tracking
        var correlationId = Guid.NewGuid().ToString();

        // 3. Publish analysis request to RabbitMQ
        var analysisEvent = new ArticleAnalysisRequestedEvent
        {
            CorrelationId = correlationId,
            Payload = new ArticlePayload
            {
                ArticleId = post.Id,
                Title = post.Title,
                Content = post.Content,
                AuthorId = post.AuthorId,
                Language = request.Language,
                TargetRegion = "TR" // Default region
            }
        };

        await eventBus.PublishAsync(
            analysisEvent,
            MessagingConstants.RoutingKeys.AiAnalysisRequested,
            cancellationToken);

        // 4. Return accepted response with correlation ID
        // Actual results will be delivered via SignalR when AI Agent completes
        return new GenerateAiSummaryCommandResponse
        {
            Result = Result.Success(),
            Summary = null, // Will be delivered via SignalR
            CorrelationId = correlationId,
            WordCount = post.Content.Split(' ', StringSplitOptions.RemoveEmptyEntries).Length,
            Message = "AI analysis request submitted. Results will be delivered via SignalR."
        };
    }
}
