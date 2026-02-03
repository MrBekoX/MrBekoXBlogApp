using BlogApp.BuildingBlocks.Messaging;
using BlogApp.BuildingBlocks.Messaging.Abstractions;
using BlogApp.BuildingBlocks.Messaging.Events.Ai;
using BlogApp.Server.Application.Common.Interfaces.Services;
using BlogApp.Server.Application.Common.Models;
using MediatR;

namespace BlogApp.Server.Application.Features.AiFeature.Commands.ImproveContentCommand;

/// <summary>
/// Handler for improving AI content using RabbitMQ event-driven architecture.
/// Publishes content improvement request to AI Agent via RabbitMQ.
/// </summary>
public class ImproveContentCommandHandler(
    IEventBus eventBus) : IRequestHandler<ImproveContentCommandRequest, ImproveContentCommandResponse>
{
    public async Task<ImproveContentCommandResponse> Handle(
        ImproveContentCommandRequest request,
        CancellationToken cancellationToken)
    {
        try
        {
            // Generate correlation ID for tracking
            var correlationId = Guid.NewGuid().ToString();

            // Publish content improvement request to RabbitMQ
            var contentImprovementEvent = new AiContentImprovementRequestedEvent
            {
                CorrelationId = correlationId,
                Payload = new AiContentImprovementPayload
                {
                    Content = request.Content,
                    UserId = request.UserId,
                    RequestedAt = DateTime.UtcNow,
                    Language = "tr" // Default language
                }
            };

            await eventBus.PublishAsync(contentImprovementEvent, MessagingConstants.RoutingKeys.AiAnalysisRequested, cancellationToken);

            return new ImproveContentCommandResponse
            {
                Data = Result.Success("AI tarafından iyileştirilmiş içerik") // Placeholder
            };
        }
        catch (Exception ex)
        {
            return new ImproveContentCommandResponse
            {
                Data = Result.Failure<string>("İçerik iyileştirilirken hata oluştu: " + ex.Message)
            };
        }
    }
}

