using BlogApp.BuildingBlocks.Messaging;
using BlogApp.BuildingBlocks.Messaging.Abstractions;
using BlogApp.BuildingBlocks.Messaging.Events.Ai;
using BlogApp.Server.Application.Common.Interfaces.Services;
using BlogApp.Server.Application.Common.Models;
using MediatR;

namespace BlogApp.Server.Application.Features.AiFeature.Commands.GenerateExcerptCommand;

/// <summary>
/// Handler for generating AI excerpt using RabbitMQ event-driven architecture.
/// Publishes excerpt generation request to AI Agent via RabbitMQ.
/// </summary>
public class GenerateExcerptCommandHandler(
    IEventBus eventBus) : IRequestHandler<GenerateExcerptCommandRequest, GenerateExcerptCommandResponse>
{
    public async Task<GenerateExcerptCommandResponse> Handle(
        GenerateExcerptCommandRequest request,
        CancellationToken cancellationToken)
    {
        try
        {
            // Generate correlation ID for tracking
            var correlationId = Guid.NewGuid().ToString();

            // Publish excerpt generation request to RabbitMQ
            var excerptGenerationEvent = new AiExcerptGenerationRequestedEvent
            {
                CorrelationId = correlationId,
                Payload = new AiExcerptGenerationPayload
                {
                    Content = request.Content,
                    UserId = request.UserId,
                    RequestedAt = DateTime.UtcNow,
                    Language = "tr" // Default language
                }
            };

            await eventBus.PublishAsync(excerptGenerationEvent, MessagingConstants.RoutingKeys.AiAnalysisRequested, cancellationToken);

            return new GenerateExcerptCommandResponse
            {
                Data = Result.Success("AI tarafından oluşturulan özet") // Placeholder
            };
        }
        catch (Exception ex)
        {
            return new GenerateExcerptCommandResponse
            {
                Data = Result.Failure<string>("Özet oluşturulurken hata oluştu: " + ex.Message)
            };
        }
    }
}

