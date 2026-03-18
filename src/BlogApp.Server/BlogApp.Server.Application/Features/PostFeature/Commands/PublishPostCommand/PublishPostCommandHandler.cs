using System.Text.Json;
using BlogApp.Server.Application.Common.BusinessRuleEngine;
using BlogApp.BuildingBlocks.Messaging;
using BlogApp.Server.Application.Common.Constants;
using BlogApp.Server.Application.Common.Events;
using BlogApp.Server.Application.Common.Interfaces.Persistence;
using BlogApp.Server.Application.Common.Interfaces.Services;
using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.Common.Utilities;
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
    IIdempotencyService idempotencyService,
    IOutboxService outboxService,
    ILogger<PublishPostCommandHandler> logger) : IRequestHandler<PublishPostCommandRequest, PublishPostCommandResponse>
{
    public async Task<PublishPostCommandResponse> Handle(PublishPostCommandRequest request, CancellationToken cancellationToken)
    {
        if (!outboxService.IsEnabled)
        {
            return new PublishPostCommandResponse
            {
                OperationId = request.OperationId,
                ErrorCode = AsyncOperationErrorCodes.AsyncDispatchUnavailable,
                ErrorMessage = "Asynchronous publishing is temporarily unavailable.",
                Result = Result.Failure("Asynchronous publishing is temporarily unavailable.")
            };
        }

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

        var requestHash = IdempotencyRequestHasher.Compute(new { request.Id });
        var correlationId = Guid.NewGuid().ToString();
        var causationId = currentUserService.CorrelationId;
        var acceptedJson = JsonSerializer.Serialize(new
        {
            operationId = request.OperationId,
            correlationId,
            status = "processing"
        });

        return await unitOfWork.ExecuteResilientAsync(async _ignored =>
        {
            await unitOfWork.BeginTransactionAsync(cancellationToken);

            try
            {
            var startResult = await idempotencyService.BeginRequestAsync(
                new IdempotencyStartRequest(
                    EndpointName: "posts.publish",
                    OperationId: request.OperationId,
                    RequestHash: requestHash,
                    CorrelationId: correlationId,
                    CausationId: causationId,
                    AcceptedHttpStatus: 202,
                    AcceptedResponseJson: acceptedJson,
                    UserId: currentUserService.UserId,
                    SessionId: null,
                    ResourceId: request.Id.ToString()),
                cancellationToken);

            switch (startResult.State)
            {
                case IdempotencyStartState.Conflict:
                    await unitOfWork.RollbackTransactionAsync(cancellationToken);
                    return new PublishPostCommandResponse
                    {
                        OperationId = request.OperationId,
                        CorrelationId = startResult.Record.CorrelationId,
                        ErrorCode = "operation_conflict",
                        ErrorMessage = "The same operationId was used with a different payload.",
                        Result = Result.Failure("The same operationId was used with a different payload.")
                    };

                case IdempotencyStartState.Completed:
                    await unitOfWork.RollbackTransactionAsync(cancellationToken);
                    return new PublishPostCommandResponse
                    {
                        OperationId = request.OperationId,
                        CorrelationId = startResult.Record.CorrelationId,
                        Result = Result.Success()
                    };

                case IdempotencyStartState.Failed:
                    await unitOfWork.RollbackTransactionAsync(cancellationToken);
                    return new PublishPostCommandResponse
                    {
                        OperationId = request.OperationId,
                        CorrelationId = startResult.Record.CorrelationId,
                        ErrorCode = startResult.Record.ErrorCode,
                        ErrorMessage = startResult.Record.ErrorMessage,
                        Result = Result.Failure(startResult.Record.ErrorMessage ?? "Publish request failed.")
                    };

                case IdempotencyStartState.Processing:
                    await unitOfWork.RollbackTransactionAsync(cancellationToken);
                    return new PublishPostCommandResponse
                    {
                        OperationId = request.OperationId,
                        CorrelationId = startResult.Record.CorrelationId,
                        IsProcessing = true,
                        ErrorMessage = "Publish request is still processing.",
                        Result = Result.Failure("Publish request is still processing.")
                    };
            }

            var post = await unitOfWork.PostsRead.GetByIdAsync(request.Id, cancellationToken);
            if (post is null)
            {
                await unitOfWork.RollbackTransactionAsync(cancellationToken);
                await PersistFailedRequestAsync(request, requestHash, correlationId, causationId, "post_not_found", PostBusinessRuleMessages.PostNotFoundGeneric, cancellationToken);
                return new PublishPostCommandResponse
                {
                    OperationId = request.OperationId,
                    CorrelationId = correlationId,
                    ErrorCode = "post_not_found",
                    ErrorMessage = PostBusinessRuleMessages.PostNotFoundGeneric,
                    Result = Result.Failure(PostBusinessRuleMessages.PostNotFoundGeneric)
                };
            }

            post.Publish();
            post.UpdatedAt = DateTime.UtcNow;
            post.UpdatedBy = currentUserService.UserName;

            await unitOfWork.PostsWrite.UpdateAsync(post, cancellationToken);
            await unitOfWork.SaveChangesAsync(cancellationToken);

            var articleEvent = new ArticlePublishedEvent
            {
                OperationId = request.OperationId,
                CorrelationId = startResult.Record.CorrelationId,
                CausationId = causationId,
                Payload = new ArticlePayload
                {
                    ArticleId = post.Id,
                    Title = post.Title,
                    Content = post.Content,
                    AuthorId = post.AuthorId,
                    Visibility = "published",
                    Language = "tr",
                    TargetRegion = "TR"
                }
            };

            var outboxMessage = await outboxService.EnqueueAsync(articleEvent, articleEvent.GetRoutingKey(), cancellationToken);
            await unitOfWork.CommitTransactionAsync(cancellationToken);

            await cacheService.RemoveAsync(PostCacheKeys.ById(post.Id), cancellationToken);
            await cacheService.RemoveAsync(PostCacheKeys.BySlug(post.Slug), cancellationToken);
            await cacheService.RotateGroupVersionAsync(PostCacheKeys.ListGroup, cancellationToken);

            await idempotencyService.MarkCompletedByCorrelationAsync(
                startResult.Record.CorrelationId,
                200,
                new { postId = post.Id, operationId = request.OperationId },
                cancellationToken);

            _ = await outboxService.TryPublishAsync(outboxMessage.Id, cancellationToken);

            logger.LogInformation(
                "[Publish] Post {PostId} ({Slug}) published. operationId={OperationId}, correlationId={CorrelationId}",
                post.Id,
                post.Slug,
                request.OperationId,
                startResult.Record.CorrelationId);

            return new PublishPostCommandResponse
            {
                OperationId = request.OperationId,
                CorrelationId = startResult.Record.CorrelationId,
                Result = Result.Success()
            };
        }
        catch (Exception ex)
        {
            if (ex is DbUpdateConcurrencyException)
            {
                await unitOfWork.RollbackTransactionAsync(cancellationToken);
                logger.LogWarning(ex, "Concurrent publish detected for post {PostId}", request.Id);
                throw new ConflictException(PostBusinessRuleMessages.PostModifiedConcurrently);
            }

            await unitOfWork.RollbackTransactionAsync(cancellationToken);
            await PersistFailedRequestAsync(request, requestHash, correlationId, causationId, "publish_failed", ex.Message, cancellationToken);
            logger.LogError(ex, "Failed to publish post {PostId} for operation {OperationId}", request.Id, request.OperationId);
            return new PublishPostCommandResponse
            {
                OperationId = request.OperationId,
                CorrelationId = correlationId,
                ErrorCode = "publish_failed",
                ErrorMessage = ex.Message,
                Result = Result.Failure(ex.Message)
            };
            }
        }, cancellationToken);
    }

    private async Task PersistFailedRequestAsync(
        PublishPostCommandRequest request,
        string requestHash,
        string correlationId,
        string? causationId,
        string errorCode,
        string errorMessage,
        CancellationToken cancellationToken)
    {
        var acceptedJson = JsonSerializer.Serialize(new
        {
            operationId = request.OperationId,
            correlationId,
            status = "processing"
        });

        var failedStart = await idempotencyService.BeginRequestAsync(
            new IdempotencyStartRequest(
                EndpointName: "posts.publish",
                OperationId: request.OperationId,
                RequestHash: requestHash,
                CorrelationId: correlationId,
                CausationId: causationId,
                AcceptedHttpStatus: 202,
                AcceptedResponseJson: acceptedJson,
                UserId: currentUserService.UserId,
                SessionId: null,
                ResourceId: request.Id.ToString()),
            cancellationToken);

        if (failedStart.State is IdempotencyStartState.Started or IdempotencyStartState.Processing or IdempotencyStartState.Failed)
        {
            await idempotencyService.MarkFailedByCorrelationAsync(failedStart.Record.CorrelationId, errorCode, errorMessage, cancellationToken);
        }
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

        var post = await unitOfWork.PostsRead.GetByIdAsync(request.Id, cancellationToken);
        if (post is null)
        {
            return new UnpublishPostCommandResponse { Result = Result.Failure(PostBusinessRuleMessages.PostNotFoundGeneric) };
        }

        post.Unpublish();
        post.UpdatedAt = DateTime.UtcNow;
        post.UpdatedBy = currentUserService.UserName;

        try
        {
            await unitOfWork.PostsWrite.UpdateAsync(post, cancellationToken);
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
        logger.LogInformation("[Unpublish] Post {PostId} ({Slug}) unpublished. Cache invalidated, SignalR notification sent.", post.Id, post.Slug);

        return new UnpublishPostCommandResponse { Result = Result.Success() };
    }
}



