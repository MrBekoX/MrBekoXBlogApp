using BlogApp.Server.Application.Common.BusinessRuleEngine;
using BlogApp.Server.Application.Common.Errors;
using BlogApp.Server.Application.Common.Interfaces.Persistence;
using BlogApp.Server.Application.Common.Interfaces.Services;
using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.Features.PostFeature.Constants;
using BlogApp.Server.Domain.Exceptions;
using BlogApp.Server.Application.Features.PostFeature.Rules;
using MediatR;
using Microsoft.EntityFrameworkCore;

namespace BlogApp.Server.Application.Features.PostFeature.Commands.DeletePostCommand;

public class DeletePostCommandHandler(
    IUnitOfWork unitOfWork,
    ICurrentUserService currentUserService,
    IPostBusinessRules postBusinessRules,
    ICacheService cacheService) : IRequestHandler<DeletePostCommandRequest, Result<Unit>>
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

        // Soft delete
        post.IsDeleted = true;
        post.DeletedAt = DateTime.UtcNow;
        post.UpdatedBy = currentUserService.UserName;

        try
        {
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



