using BlogApp.Core.Application.Common.Interfaces.Persistence;
using BlogApp.Core.Application.Common.Interfaces.Services;
using BlogApp.Core.Application.Common.Security;
using BlogApp.Core.Domain.Enums;
using Microsoft.EntityFrameworkCore;

namespace BlogApp.Infrastructure.Services;

public sealed class PostAuthorizationService(IUnitOfWork unitOfWork) : IPostAuthorizationService
{
    public async Task<PostAuthorizationDecision> AuthorizeAsync(
        Guid postId,
        PostAuthorizationSubject subject,
        PostAuthorizationAction action,
        CancellationToken cancellationToken = default)
    {
        var post = await unitOfWork.PostsRead.Query()
            .AsNoTracking()
            .Where(value => value.Id == postId && !value.IsDeleted)
            .Select(value => new
            {
                value.Id,
                value.AuthorId,
                value.Status
            })
            .FirstOrDefaultAsync(cancellationToken);

        if (post is null)
        {
            return PostAuthorizationDecision.NotFound(postId);
        }

        var isStaff = subject.IsInRole("Admin") || subject.IsInRole("Editor");
        var isOwner = subject.UserId.HasValue && subject.UserId.Value == post.AuthorId;
        var isAuthorized = action switch
        {
            PostAuthorizationAction.ViewPublished =>
                post.Status == PostStatus.Published || isOwner || isStaff,
            PostAuthorizationAction.ViewUnpublished =>
                isOwner || isStaff,
            PostAuthorizationAction.Edit =>
                isOwner || isStaff,
            _ => false
        };

        return new PostAuthorizationDecision(
            true,
            isAuthorized,
            post.Id,
            post.AuthorId,
            post.Status);
    }
}
