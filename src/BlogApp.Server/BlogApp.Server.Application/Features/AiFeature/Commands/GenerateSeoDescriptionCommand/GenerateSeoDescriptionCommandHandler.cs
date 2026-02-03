using BlogApp.BuildingBlocks.Messaging;
using BlogApp.BuildingBlocks.Messaging.Abstractions;
using BlogApp.BuildingBlocks.Messaging.Events.Ai;
using BlogApp.Server.Application.Common.Interfaces.Services;
using BlogApp.Server.Application.Common.Models;
using MediatR;

namespace BlogApp.Server.Application.Features.AiFeature.Commands.GenerateSeoDescriptionCommand;

/// <summary>
/// Handler for generating AI SEO description using RabbitMQ event-driven architecture.
/// Publishes SEO description generation request to AI Agent via RabbitMQ.
/// </summary>
public class GenerateSeoDescriptionCommandHandler(
    IEventBus eventBus) : IRequestHandler<GenerateSeoDescriptionCommandRequest, GenerateSeoDescriptionCommandResponse>
{
    public async Task<GenerateSeoDescriptionCommandResponse> Handle(
        GenerateSeoDescriptionCommandRequest request,
        CancellationToken cancellationToken)
    {
        try
        {
            // Generate correlation ID for tracking
            var correlationId = Guid.NewGuid().ToString();

            // Publish SEO description generation request to RabbitMQ
            var seoGenerationEvent = new AiSeoDescriptionGenerationRequestedEvent
            {
                CorrelationId = correlationId,
                Payload = new AiSeoDescriptionGenerationPayload
                {
                    Content = request.Content,
                    UserId = request.UserId,
                    RequestedAt = DateTime.UtcNow,
                    Language = "tr" // Default language
                }
            };

            await eventBus.PublishAsync(seoGenerationEvent, MessagingConstants.RoutingKeys.AiAnalysisRequested, cancellationToken);

            return new GenerateSeoDescriptionCommandResponse
            {
                Data = Result.Success("AI tarafından oluşturulan SEO açıklaması") // Placeholder
            };
        }
        catch (Exception ex)
        {
            return new GenerateSeoDescriptionCommandResponse
            {
                Data = Result.Failure<string>("SEO açıklaması oluşturulurken hata oluştu: " + ex.Message)
            };
        }
    }
}

