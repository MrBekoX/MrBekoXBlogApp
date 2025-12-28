using BlogApp.Server.Application.Common.BusinessRuleEngine;
using BlogApp.Server.Application.Common.Interfaces;
using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.Features.PostFeature.Constants;
using BlogApp.Server.Application.Features.PostFeature.Rules;
using MediatR;

namespace BlogApp.Server.Application.Features.PostFeature.Commands.PublishPostCommand;

public class PublishPostCommandHandler(
    IUnitOfWork unitOfWork,
    ICacheService cacheService,
    IPostBusinessRules postBusinessRules) : IRequestHandler<PublishPostCommandRequest, PublishPostCommandResponse>
{
    public async Task<PublishPostCommandResponse> Handle(PublishPostCommandRequest request, CancellationToken cancellationToken)
    {
        // Business Rules
        var ruleResult = await BusinessRuleEngine.RunAsync(
            async () => await postBusinessRules.CheckPostExistsAsync(request.Id)
        );

        if (!ruleResult.IsSuccess)
        {
            return new PublishPostCommandResponse
            {
                Result = Result.Failure(ruleResult.Error!)
            };
        }

        var post = await unitOfWork.PostsRead.GetByIdAsync(request.Id, cancellationToken);
        if (post is null)
        {
            return new PublishPostCommandResponse
            {
                Result = Result.Failure(PostBusinessRuleMessages.PostNotFoundGeneric)
            };
        }

        post.Publish();

        await unitOfWork.PostsWrite.UpdateAsync(post, cancellationToken);
        await unitOfWork.SaveChangesAsync(cancellationToken);

        // Cache'i temizle
        await cacheService.RemoveByPrefixAsync("posts:list", cancellationToken);
        await cacheService.RemoveByPrefixAsync("posts-list", cancellationToken);

        return new PublishPostCommandResponse
        {
            Result = Result.Success()
        };
    }
}

public class UnpublishPostCommandHandler(
    IUnitOfWork unitOfWork,
    ICacheService cacheService,
    IPostBusinessRules postBusinessRules) : IRequestHandler<UnpublishPostCommandRequest, UnpublishPostCommandResponse>
{
    public async Task<UnpublishPostCommandResponse> Handle(UnpublishPostCommandRequest request, CancellationToken cancellationToken)
    {
        // Business Rules
        var ruleResult = await BusinessRuleEngine.RunAsync(
            async () => await postBusinessRules.CheckPostExistsAsync(request.Id)
        );

        if (!ruleResult.IsSuccess)
        {
            return new UnpublishPostCommandResponse
            {
                Result = Result.Failure(ruleResult.Error!)
            };
        }

        var post = await unitOfWork.PostsRead.GetByIdAsync(request.Id, cancellationToken);
        if (post is null)
        {
            return new UnpublishPostCommandResponse
            {
                Result = Result.Failure(PostBusinessRuleMessages.PostNotFoundGeneric)
            };
        }

        post.Unpublish();

        await unitOfWork.PostsWrite.UpdateAsync(post, cancellationToken);
        await unitOfWork.SaveChangesAsync(cancellationToken);

        // Cache'i temizle
        await cacheService.RemoveByPrefixAsync("posts:list", cancellationToken);
        await cacheService.RemoveByPrefixAsync("posts-list", cancellationToken);

        return new UnpublishPostCommandResponse
        {
            Result = Result.Success()
        };
    }
}
