using BlogApp.Server.Application.Common.Interfaces.Persistence;
using BlogApp.Server.Application.Common.Interfaces.Services;
using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.Features.PostFeature.Constants;
using MediatR;

namespace BlogApp.Server.Application.Features.PostFeature.Commands.UpdateAiAnalysisCommand;

/// <summary>
/// Handler for updating AI analysis results.
/// Called by AI Agent Service after processing an article.
/// </summary>
public class UpdateAiAnalysisCommandHandler(
    IUnitOfWork unitOfWork,
    ICacheService cacheService) : IRequestHandler<UpdateAiAnalysisCommandRequest, UpdateAiAnalysisCommandResponse>
{
    public async Task<UpdateAiAnalysisCommandResponse> Handle(
        UpdateAiAnalysisCommandRequest request,
        CancellationToken cancellationToken)
    {
        // 1. Get post by ID
        var post = await unitOfWork.PostsRead.GetByIdAsync(request.PostId, cancellationToken);
        if (post is null)
        {
            return new UpdateAiAnalysisCommandResponse
            {
                Result = Result.Failure(PostBusinessRuleMessages.PostNotFoundGeneric)
            };
        }

        // 2. Update AI fields
        if (request.AiSummary is not null)
            post.AiSummary = request.AiSummary;

        if (request.AiKeywords is not null)
            post.AiKeywords = request.AiKeywords;

        if (request.AiEstimatedReadingTime.HasValue)
            post.AiEstimatedReadingTime = request.AiEstimatedReadingTime.Value;

        if (request.AiSeoDescription is not null)
            post.AiSeoDescription = request.AiSeoDescription;

        if (request.AiGeoOptimization is not null)
            post.AiGeoOptimization = request.AiGeoOptimization;

        // Set processing timestamp
        post.AiProcessedAt = DateTime.UtcNow;

        // 3. Save changes
        await unitOfWork.PostsWrite.UpdateAsync(post, cancellationToken);
        await unitOfWork.SaveChangesAsync(cancellationToken);

        // 4. Invalidate caches
        await cacheService.RemoveAsync(PostCacheKeys.ById(post.Id), cancellationToken);
        await cacheService.RemoveAsync(PostCacheKeys.BySlug(post.Slug), cancellationToken);
        await cacheService.RotateGroupVersionAsync(PostCacheKeys.ListGroup, cancellationToken);

        return new UpdateAiAnalysisCommandResponse { Result = Result.Success() };
    }
}
