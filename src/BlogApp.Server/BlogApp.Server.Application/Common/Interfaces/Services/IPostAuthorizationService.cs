using BlogApp.Server.Application.Common.Security;

namespace BlogApp.Server.Application.Common.Interfaces.Services;

public interface IPostAuthorizationService
{
    Task<PostAuthorizationDecision> AuthorizeAsync(
        Guid postId,
        PostAuthorizationSubject subject,
        PostAuthorizationAction action,
        CancellationToken cancellationToken = default);
}
