using BlogApp.Server.Application.Common.BusinessRuleEngine;
using BlogApp.Server.Application.Common.Interfaces.Persistence;
using BlogApp.Server.Application.Common.Interfaces.Services;
using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.Features.PostFeature.Constants;
using BlogApp.Server.Application.Features.PostFeature.Rules;
using BlogApp.Server.Domain.Exceptions;
using MediatR;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging;

namespace BlogApp.Server.Application.Features.PostFeature.Commands.PublishPostCommand;

public class PublishPostCommandHandler(
    IUnitOfWork unitOfWork,
    ICacheService cacheService,
    IPostBusinessRules postBusinessRules,
    ICurrentUserService currentUserService,
    ILogger<PublishPostCommandHandler> logger) : IRequestHandler<PublishPostCommandRequest, PublishPostCommandResponse>
{
    public async Task<PublishPostCommandResponse> Handle(PublishPostCommandRequest request, CancellationToken cancellationToken)
    {
        var ruleResult = await BusinessRuleEngine.RunAsync(
            async () => await postBusinessRules.CheckPostExistsAsync(request.Id)
        );

        if (!ruleResult.IsSuccess)
        {
            return new PublishPostCommandResponse
            {
                OperationId = request.OperationId,
                ErrorCode = "post_not_found",
                ErrorMessage = ruleResult.Error,
                Result = Result.Failure(ruleResult.Error!)
            };
        }

        // Use AsTracking() to get a tracked entity — prevents TOCTOU race condition
        var post = await unitOfWork.PostsRead.Query()
            .AsTracking()
            .FirstOrDefaultAsync(p => p.Id == request.Id, cancellationToken);
        if (post is null)
        {
            return new PublishPostCommandResponse
            {
                OperationId = request.OperationId,
                ErrorCode = "post_not_found",
                ErrorMessage = PostBusinessRuleMessages.PostNotFoundGeneric,
                Result = Result.Failure(PostBusinessRuleMessages.PostNotFoundGeneric)
            };
        }

        post.Publish();
        post.UpdatedAt = DateTime.UtcNow;
        post.UpdatedBy = currentUserService.UserName;

        try
        {
            await unitOfWork.SaveChangesAsync(cancellationToken);
        }
        catch (DbUpdateConcurrencyException ex)
        {
            logger.LogWarning(ex, "Concurrent publish detected for post {PostId}", request.Id);
            throw new ConflictException(PostBusinessRuleMessages.PostModifiedConcurrently);
        }

        await cacheService.RemoveAsync(PostCacheKeys.ById(post.Id), cancellationToken);
        await cacheService.RemoveAsync(PostCacheKeys.BySlug(post.Slug), cancellationToken);
        await cacheService.RotateGroupVersionAsync(PostCacheKeys.ListGroup, cancellationToken);

        logger.LogInformation(
            "[Publish] Post {PostId} ({Slug}) published. operationId={OperationId}",
            post.Id, post.Slug, request.OperationId);

        return new PublishPostCommandResponse
        {
            OperationId = request.OperationId,
            Result = Result.Success()
        };
    }
}

public class UnpublishPostCommandHandler(
    IUnitOfWork unitOfWork,
    ICacheService cacheService,
    IPostBusinessRules postBusinessRules,
    ICurrentUserService currentUserService,
    ILogger<UnpublishPostCommandHandler> logger) : IRequestHandler<UnpublishPostCommandRequest, UnpublishPostCommandResponse>
{
    public async Task<UnpublishPostCommandResponse> Handle(UnpublishPostCommandRequest request, CancellationToken cancellationToken)
    {
        var ruleResult = await BusinessRuleEngine.RunAsync(
            async () => await postBusinessRules.CheckPostExistsAsync(request.Id)
        );

        if (!ruleResult.IsSuccess)
        {
            return new UnpublishPostCommandResponse { Result = Result.Failure(ruleResult.Error!) };
        }

        // Use AsTracking() to get a tracked entity — prevents TOCTOU race condition
        var post = await unitOfWork.PostsRead.Query()
            .AsTracking()
            .FirstOrDefaultAsync(p => p.Id == request.Id, cancellationToken);
        if (post is null)
        {
            return new UnpublishPostCommandResponse { Result = Result.Failure(PostBusinessRuleMessages.PostNotFoundGeneric) };
        }

        post.Unpublish();
        post.UpdatedAt = DateTime.UtcNow;
        post.UpdatedBy = currentUserService.UserName;

        try
        {
            await unitOfWork.SaveChangesAsync(cancellationToken);
        }
        catch (DbUpdateConcurrencyException ex)
        {
            logger.LogWarning(ex, "Concurrent unpublish detected for post {PostId}", request.Id);
            throw new ConflictException(PostBusinessRuleMessages.PostModifiedConcurrently);
        }

        await cacheService.RemoveAsync(PostCacheKeys.ById(post.Id), cancellationToken);
        await cacheService.RemoveAsync(PostCacheKeys.BySlug(post.Slug), cancellationToken);
        await cacheService.RotateGroupVersionAsync(PostCacheKeys.ListGroup, cancellationToken);

        logger.LogInformation("[Unpublish] Post {PostId} ({Slug}) unpublished.", post.Id, post.Slug);

        return new UnpublishPostCommandResponse { Result = Result.Success() };
    }
}
