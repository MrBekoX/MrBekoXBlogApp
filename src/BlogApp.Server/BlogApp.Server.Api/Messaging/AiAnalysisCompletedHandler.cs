using System.Text.Json;
using BlogApp.BuildingBlocks.Messaging.Abstractions;
using BlogApp.Server.Api.Hubs;
using BlogApp.Server.Application.Common.Events;
using BlogApp.Server.Application.Common.Interfaces.Persistence;
using BlogApp.Server.Application.Common.Interfaces.Services;
using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.Features.PostFeature.Constants;
using Microsoft.AspNetCore.SignalR;
using Microsoft.EntityFrameworkCore;

namespace BlogApp.Server.Api.Messaging;

public class AiAnalysisCompletedHandler : IEventHandler<AiAnalysisCompletedEvent>
{
    private const string ConsumerName = "backend.ai-analysis-completed-handler";

    private readonly IServiceProvider _serviceProvider;
    private readonly IHubContext<AuthoringEventsHub> _hubContext;
    private readonly IIdempotencyService _idempotencyService;
    private readonly ILogger<AiAnalysisCompletedHandler> _logger;

    public AiAnalysisCompletedHandler(
        IServiceProvider serviceProvider,
        IHubContext<AuthoringEventsHub> hubContext,
        IIdempotencyService idempotencyService,
        ILogger<AiAnalysisCompletedHandler> logger)
    {
        _serviceProvider = serviceProvider;
        _hubContext = hubContext;
        _idempotencyService = idempotencyService;
        _logger = logger;
    }

    public async Task HandleAsync(AiAnalysisCompletedEvent @event, CancellationToken cancellationToken = default)
    {
        var operationId = @event.OperationId ?? @event.MessageId.ToString();
        var claim = await _idempotencyService.ClaimConsumerAsync(
            ConsumerName,
            operationId,
            @event.MessageId,
            @event.CorrelationId,
            cancellationToken);

        if (claim.State is ConsumerClaimState.DuplicateCompleted or ConsumerClaimState.DuplicateProcessing)
        {
            _logger.LogInformation(
                "Skipping duplicate AI analysis completion for operation {OperationId} ({State})",
                operationId,
                claim.State);
            return;
        }

        var postId = @event.Payload.PostId;
        var correlationId = @event.CorrelationId;

        try
        {
            using var scope = _serviceProvider.CreateScope();
            var unitOfWork = scope.ServiceProvider.GetRequiredService<IUnitOfWork>();

            var post = await unitOfWork.PostsRead.GetByIdAsync(postId, cancellationToken);
            if (post is null)
            {
                _logger.LogWarning("Post {PostId} not found, skipping AI analysis update", postId);
                await _idempotencyService.MarkConsumerCompletedAsync(claim.Record.Id, cancellationToken);
                return;
            }

            post.AiSummary = @event.Payload.Summary;
            post.AiKeywords = string.Join(",", @event.Payload.Keywords);
            post.AiSeoDescription = @event.Payload.SeoDescription;
            post.AiEstimatedReadingTime = (int)Math.Round(@event.Payload.ReadingTime);
            post.AiProcessedAt = DateTime.UtcNow;

            if (@event.Payload.GeoOptimization is not null)
            {
                post.AiGeoOptimization = JsonSerializer.Serialize(@event.Payload.GeoOptimization);
            }

            await unitOfWork.PostsWrite.UpdateAsync(post, cancellationToken);
            await unitOfWork.SaveChangesAsync(cancellationToken);

            var responseData = new
            {
                PostId = postId,
                OperationId = operationId,
                CorrelationId = correlationId,
                Summary = @event.Payload.Summary,
                Keywords = @event.Payload.Keywords,
                SeoDescription = @event.Payload.SeoDescription,
                ReadingTime = @event.Payload.ReadingTime,
                Sentiment = @event.Payload.Sentiment,
                Timestamp = DateTime.UtcNow
            };

            await _hubContext.Clients.Group($"post_{postId}").SendAsync(
                "AiAnalysisCompleted",
                responseData,
                cancellationToken);

            if (!string.IsNullOrWhiteSpace(correlationId))
            {
                await _idempotencyService.MarkCompletedByCorrelationAsync(correlationId, StatusCodes.Status200OK, responseData, cancellationToken);
            }

            await _idempotencyService.MarkConsumerCompletedAsync(claim.Record.Id, cancellationToken);
        }
        catch (DbUpdateConcurrencyException ex)
        {
            await _idempotencyService.MarkConsumerFailedAsync(claim.Record.Id, PostBusinessRuleMessages.PostModifiedConcurrently, cancellationToken);
            _logger.LogWarning(ex, "Concurrent AI analysis update detected for post {PostId}", postId);
            throw;
        }
        catch (Exception ex)
        {
            await _idempotencyService.MarkConsumerFailedAsync(claim.Record.Id, ex.Message, cancellationToken);
            _logger.LogError(ex, "Error updating AI analysis for post {PostId}", postId);
            throw;
        }
    }
}
