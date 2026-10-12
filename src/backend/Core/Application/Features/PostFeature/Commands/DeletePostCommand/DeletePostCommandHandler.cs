using BlogApp.Core.Application.Common.BusinessRuleEngine;
using BlogApp.Core.Application.Common.Errors;
using BlogApp.Core.Application.Common.Interfaces.Messaging;
using BlogApp.Core.Application.Common.Interfaces.Persistence;
using BlogApp.Core.Application.Common.Interfaces.Services;
using BlogApp.Core.Application.Common.Models;
using BlogApp.Core.Application.Features.PostFeature.Constants;
using BlogApp.Core.Domain.Exceptions;
using BlogApp.Core.Application.Features.PostFeature.Rules;
using MediatR;
using Microsoft.EntityFrameworkCore;

namespace BlogApp.Core.Application.Features.PostFeature.Commands.DeletePostCommand;

public class DeletePostCommandHandler(
    IUnitOfWork unitOfWork,
    ICurrentUserService currentUserService,
    IPostBusinessRules postBusinessRules,
    ICacheService cacheService,
    IAgentContentEventService contentEvents) : IRequestHandler<DeletePostCommandRequest, Result<Unit>>
{
    public async Task<Result<Unit>> Handle(DeletePostCommandRequest request, CancellationToken cancellationToken)
    {
        // Business Rules
        var ruleResult = await BusinessRuleEngine.RunAsync(
            async () => await postBusinessRules.CheckPostExistsAsync(request.Id)
        );

        if (!ruleResult.IsSuccess)
        {
            return Result<Unit>.Failure(Error.NotFound(ruleResult.Error!));
        }

        var post = await unitOfWork.PostsRead.GetByIdAsync(request.Id, cancellationToken);
        if (post is null)
        {
            return Result<Unit>.Failure(Error.NotFound(PostBusinessRuleMessages.PostNotFoundGeneric));
        }

        // B8: yayımlanmış makalenin silinmesi kaldırma TOMBSTONE'u üretir; taslak silinmesi olay üretmez.
        var contentBefore = contentEvents.Observe(post);

        // Soft delete
        post.IsDeleted = true;
        post.DeletedAt = DateTime.UtcNow;
        post.UpdatedBy = currentUserService.UserName;

        try
        {
            await contentEvents.RecordChangeAsync(post, contentBefore, cancellationToken);
            await unitOfWork.PostsWrite.UpdateAsync(post, cancellationToken);
            await unitOfWork.SaveChangesAsync(cancellationToken);
        }
        catch (DbUpdateConcurrencyException)
        {
            return Result<Unit>.Failure(Error.Conflict(PostBusinessRuleMessages.PostModifiedConcurrently));
        }

        // Cache invalidation
        await cacheService.RemoveAsync(PostCacheKeys.ById(post.Id), cancellationToken);
        await cacheService.RemoveAsync(PostCacheKeys.BySlug(post.Slug), cancellationToken);
        await cacheService.RotateGroupVersionAsync(PostCacheKeys.ListGroup, cancellationToken);

        return Result<Unit>.Success(Unit.Value);
    }
}



