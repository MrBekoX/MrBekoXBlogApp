using BlogApp.Core.Application.Common.BusinessRuleEngine;
using BlogApp.Core.Application.Common.Errors;
using BlogApp.Core.Application.Common.Interfaces.Persistence;
using BlogApp.Core.Application.Common.Interfaces.Services;
using BlogApp.Core.Application.Common.Models;
using BlogApp.Core.Application.Features.PostFeature.Constants;
using BlogApp.Core.Application.Features.PostFeature.Rules;
using BlogApp.Core.Domain.Exceptions;
using MediatR;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging;

namespace BlogApp.Core.Application.Features.PostFeature.Commands.PublishPostCommand;

public class PublishPostCommandHandler(
    IUnitOfWork unitOfWork,
    ICacheService cacheService,
    IPostBusinessRules postBusinessRules,
    ICurrentUserService currentUserService,
    ILogger<PublishPostCommandHandler> logger) : IRequestHandler<PublishPostCommandRequest, Result<Unit>>
{
    public async Task<Result<Unit>> Handle(PublishPostCommandRequest request, CancellationToken cancellationToken)
    {
        var ruleResult = await BusinessRuleEngine.RunAsync(
            async () => await postBusinessRules.CheckPostExistsAsync(request.Id)
        );

        if (!ruleResult.IsSuccess)
        {
            return Result<Unit>.Failure(Error.NotFound(ruleResult.Error!));
        }

        // Use AsTracking() to get a tracked entity — prevents TOCTOU race condition
        var post = await unitOfWork.PostsRead.Query()
            .AsTracking()
            .FirstOrDefaultAsync(p => p.Id == request.Id, cancellationToken);
        if (post is null)
        {
            return Result<Unit>.Failure(Error.NotFound(PostBusinessRuleMessages.PostNotFoundGeneric));
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
            return Result<Unit>.Failure(Error.Conflict(PostBusinessRuleMessages.PostModifiedConcurrently));
        }

        await cacheService.RemoveAsync(PostCacheKeys.ById(post.Id), cancellationToken);
        await cacheService.RemoveAsync(PostCacheKeys.BySlug(post.Slug), cancellationToken);
        await cacheService.RotateGroupVersionAsync(PostCacheKeys.ListGroup, cancellationToken);

        logger.LogInformation(
            "[Publish] Post {PostId} ({Slug}) published. operationId={OperationId}",
            post.Id, post.Slug, request.OperationId);

        return Result<Unit>.Success(Unit.Value);
    }
}

public class UnpublishPostCommandHandler(
    IUnitOfWork unitOfWork,
    ICacheService cacheService,
    IPostBusinessRules postBusinessRules,
    ICurrentUserService currentUserService,
    ILogger<UnpublishPostCommandHandler> logger) : IRequestHandler<UnpublishPostCommandRequest, Result<Unit>>
{
    public async Task<Result<Unit>> Handle(UnpublishPostCommandRequest request, CancellationToken cancellationToken)
    {
        var ruleResult = await BusinessRuleEngine.RunAsync(
            async () => await postBusinessRules.CheckPostExistsAsync(request.Id)
        );

        if (!ruleResult.IsSuccess)
        {
            return Result<Unit>.Failure(Error.NotFound(ruleResult.Error!));
        }

        // Use AsTracking() to get a tracked entity — prevents TOCTOU race condition
        var post = await unitOfWork.PostsRead.Query()
            .AsTracking()
            .FirstOrDefaultAsync(p => p.Id == request.Id, cancellationToken);
        if (post is null)
        {
            return Result<Unit>.Failure(Error.NotFound(PostBusinessRuleMessages.PostNotFoundGeneric));
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
            return Result<Unit>.Failure(Error.Conflict(PostBusinessRuleMessages.PostModifiedConcurrently));
        }

        await cacheService.RemoveAsync(PostCacheKeys.ById(post.Id), cancellationToken);
        await cacheService.RemoveAsync(PostCacheKeys.BySlug(post.Slug), cancellationToken);
        await cacheService.RotateGroupVersionAsync(PostCacheKeys.ListGroup, cancellationToken);

        logger.LogInformation("[Unpublish] Post {PostId} ({Slug}) unpublished.", post.Id, post.Slug);

        return Result<Unit>.Success(Unit.Value);
    }
}
