using BlogApp.Server.Application.Common.Interfaces.Persistence;
using BlogApp.Server.Application.Common.Interfaces.Services;
using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.Features.PostFeature.Constants;
using BlogApp.Server.Domain.Enums;

namespace BlogApp.Server.Application.Features.PostFeature.Rules;

public class PostBusinessRules : IPostBusinessRules
{
    private readonly IUnitOfWork _unitOfWork;

    public PostBusinessRules(IUnitOfWork unitOfWork)
    {
        _unitOfWork = unitOfWork;
    }

    public async Task<Result> CheckPostExistsAsync(Guid postId)
    {
        var post = await _unitOfWork.PostsRead.GetByIdAsync(postId);

        return post is not null && !post.IsDeleted
            ? Result.Success()
            : Result.Failure(PostBusinessRuleMessages.PostNotFound(postId));
    }

    public async Task<Result> CheckUserCanEditPostAsync(Guid postId, Guid userId)
    {
        var post = await _unitOfWork.PostsRead.GetByIdAsync(postId);

        if (post is null || post.IsDeleted)
            return Result.Failure(PostBusinessRuleMessages.PostNotFound(postId));

        if (post.AuthorId != userId)
            return Result.Failure(PostBusinessRuleMessages.UnauthorizedToEditPost);

        return Result.Success();
    }

    public async Task<Result> CheckUserCanDeletePostAsync(Guid postId, Guid userId)
    {
        var post = await _unitOfWork.PostsRead.GetByIdAsync(postId);

        if (post is null || post.IsDeleted)
            return Result.Failure(PostBusinessRuleMessages.PostNotFound(postId));

        if (post.AuthorId != userId)
            return Result.Failure(PostBusinessRuleMessages.UnauthorizedToDeletePost);

        return Result.Success();
    }

    public async Task<Result> CheckPostIsNotPublishedAsync(Guid postId)
    {
        var post = await _unitOfWork.PostsRead.GetByIdAsync(postId);

        if (post is null || post.IsDeleted)
            return Result.Failure(PostBusinessRuleMessages.PostNotFound(postId));

        if (post.Status == PostStatus.Published)
            return Result.Failure(PostBusinessRuleMessages.CannotDeletePublishedPost);

        return Result.Success();
    }
}


