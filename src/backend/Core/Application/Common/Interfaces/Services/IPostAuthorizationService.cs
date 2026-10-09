using BlogApp.Core.Application.Common.Security;

namespace BlogApp.Core.Application.Common.Interfaces.Services;

public interface IPostAuthorizationService
{
    Task<PostAuthorizationDecision> AuthorizeAsync(
        Guid postId,
        PostAuthorizationSubject subject,
        PostAuthorizationAction action,
        CancellationToken cancellationToken = default);
}
