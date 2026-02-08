using System.Text.Json;
using BlogApp.BuildingBlocks.Messaging.Abstractions;
using BlogApp.Server.Api.Hubs;
using BlogApp.Server.Application.Common.Events;
using BlogApp.Server.Application.Common.Interfaces.Persistence;
using Microsoft.AspNetCore.SignalR;

namespace BlogApp.Server.Api.Messaging;

/// <summary>
/// Handles AI analysis completed events from RabbitMQ.
/// Updates the post with AI analysis results and notifies clients via SignalR.
/// </summary>
public class AiAnalysisCompletedHandler : IEventHandler<AiAnalysisCompletedEvent>
{
    private readonly IServiceProvider _serviceProvider;
    private readonly IHubContext<CacheInvalidationHub> _hubContext;
    private readonly ILogger<AiAnalysisCompletedHandler> _logger;

    public AiAnalysisCompletedHandler(
        IServiceProvider serviceProvider,
        IHubContext<CacheInvalidationHub> hubContext,
        ILogger<AiAnalysisCompletedHandler> logger)
    {
        _serviceProvider = serviceProvider;
        _hubContext = hubContext;
        _logger = logger;
    }

    public async Task HandleAsync(AiAnalysisCompletedEvent @event, CancellationToken cancellationToken = default)
    {
        var postId = @event.Payload.PostId;
        var correlationId = @event.CorrelationId;

        _logger.LogInformation(
            "Processing AI analysis completed event for post {PostId} (CorrelationId: {CorrelationId})",
            postId,
            correlationId);

        try
        {
            // Create a new scope for database operations
            using var scope = _serviceProvider.CreateScope();
            var unitOfWork = scope.ServiceProvider.GetRequiredService<IUnitOfWork>();

            // Get the post
            var post = await unitOfWork.PostsRead.GetByIdAsync(postId, cancellationToken);
            if (post is null)
            {
                _logger.LogWarning("Post {PostId} not found, skipping AI analysis update", postId);
                return;
            }

            // Update AI analysis fields
            post.AiSummary = @event.Payload.Summary;
            post.AiKeywords = string.Join(",", @event.Payload.Keywords);
            post.AiSeoDescription = @event.Payload.SeoDescription;
            post.AiEstimatedReadingTime = (int)Math.Round(@event.Payload.ReadingTime);
            post.AiProcessedAt = DateTime.UtcNow;

            // Update GEO optimization if available
            if (@event.Payload.GeoOptimization is not null)
            {
                post.AiGeoOptimization = JsonSerializer.Serialize(@event.Payload.GeoOptimization);
            }

            // Save changes
            await unitOfWork.PostsWrite.UpdateAsync(post, cancellationToken);
            await unitOfWork.SaveChangesAsync(cancellationToken);

            _logger.LogInformation(
                "Successfully updated AI analysis for post {PostId}",
                postId);

            // Notify only clients subscribed to this post's analysis
            await _hubContext.Clients.Group($"post_{postId}").SendAsync(
                "AiAnalysisCompleted",
                new
                {
                    PostId = postId,
                    CorrelationId = correlationId,
                    Summary = @event.Payload.Summary,
                    Keywords = @event.Payload.Keywords,
                    SeoDescription = @event.Payload.SeoDescription,
                    ReadingTime = @event.Payload.ReadingTime,
                    Sentiment = @event.Payload.Sentiment,
                    Timestamp = DateTime.UtcNow
                },
                cancellationToken);
        }
        catch (Exception ex)
        {
            _logger.LogError(
                ex,
                "Error updating AI analysis for post {PostId}",
                postId);
            throw; // Let the consumer handle retry logic
        }
    }
}
