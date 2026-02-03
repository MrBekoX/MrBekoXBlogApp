using BlogApp.BuildingBlocks.Messaging;
using BlogApp.BuildingBlocks.Messaging.Abstractions;
using BlogApp.BuildingBlocks.Messaging.Events.Ai;
using BlogApp.Server.Application.Common.Interfaces.Services;
using BlogApp.Server.Application.Common.Models;
using MediatR;

namespace BlogApp.Server.Application.Features.AiFeature.Commands.GenerateTagsCommand;

/// <summary>
/// Handler for generating AI tags using RabbitMQ event-driven architecture.
/// Publishes tags generation request to AI Agent via RabbitMQ.
/// </summary>
public class GenerateTagsCommandHandler(
    IEventBus eventBus) : IRequestHandler<GenerateTagsCommandRequest, GenerateTagsCommandResponse>
{
    public async Task<GenerateTagsCommandResponse> Handle(
        GenerateTagsCommandRequest request,
        CancellationToken cancellationToken)
    {
        try
        {
            // Generate correlation ID for tracking
            var correlationId = Guid.NewGuid().ToString();

            // Publish tags generation request to RabbitMQ
            var tagsGenerationEvent = new AiTagsGenerationRequestedEvent
            {
                CorrelationId = correlationId,
                Payload = new AiTagsGenerationPayload
                {
                    Content = request.Content,
                    UserId = request.UserId,
                    RequestedAt = DateTime.UtcNow,
                    Language = "tr" // Default language
                }
            };

            await eventBus.PublishAsync(tagsGenerationEvent, MessagingConstants.RoutingKeys.AiAnalysisRequested, cancellationToken);

            return new GenerateTagsCommandResponse
            {
                Data = Result.Success(new[] { "etiket1", "etiket2", "etiket3" }) // Placeholder
            };
        }
        catch (Exception ex)
        {
            return new GenerateTagsCommandResponse
            {
                Data = Result.Failure<string[]>("Etiketler oluşturulurken hata oluştu: " + ex.Message)
            };
        }
    }
}

