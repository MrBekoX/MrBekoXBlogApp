using BlogApp.BuildingBlocks.Messaging;
using BlogApp.BuildingBlocks.Messaging.Abstractions;
using BlogApp.BuildingBlocks.Messaging.Events.Ai;
using BlogApp.Server.Application.Common.Interfaces.Services;
using BlogApp.Server.Application.Common.Models;
using MediatR;

namespace BlogApp.Server.Application.Features.AiFeature.Commands.GenerateTitleCommand;

/// <summary>
/// Handler for generating AI title using RabbitMQ event-driven architecture.
/// Publishes title generation request to AI Agent via RabbitMQ.
/// </summary>
public class GenerateTitleCommandHandler(
    IEventBus eventBus) : IRequestHandler<GenerateTitleCommandRequest, GenerateTitleCommandResponse>
{
    public async Task<GenerateTitleCommandResponse> Handle(
        GenerateTitleCommandRequest request,
        CancellationToken cancellationToken)
    {
        try
        {
            // Generate correlation ID for tracking
            var correlationId = Guid.NewGuid().ToString();

            // Publish title generation request to RabbitMQ
            var titleGenerationEvent = new AiTitleGenerationRequestedEvent
            {
                CorrelationId = correlationId,
                Payload = new AiTitleGenerationPayload
                {
                    Content = request.Content,
                    UserId = request.UserId,
                    RequestedAt = DateTime.UtcNow,
                    Language = "tr" // Default language
                }
            };

            await eventBus.PublishAsync(titleGenerationEvent, MessagingConstants.RoutingKeys.AiAnalysisRequested, cancellationToken);

            // For now, return a mock response - in real implementation, 
            // we would wait for the response from AI Agent service
            // This could be implemented with a temporary response or polling mechanism
            
            return new GenerateTitleCommandResponse
            {
                Data = Result.Success("AI tarafından oluşturulan başlık") // Placeholder
            };
        }
        catch (Exception ex)
        {
            return new GenerateTitleCommandResponse
            {
                Data = Result.Failure<string>("Başlık oluşturulurken hata oluştu: " + ex.Message)
            };
        }
    }
}
