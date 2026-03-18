using BlogApp.Server.Domain.Enums;

namespace BlogApp.Server.Application.Common.Security;

public enum PostAuthorizationAction
{
    ViewPublished,
    ViewUnpublished,
    Edit,
    TriggerAi,
    ReceiveAiEvents
}

public sealed record PostAuthorizationSubject(
    Guid? UserId,
    bool IsAuthenticated,
    IReadOnlyCollection<string> Roles)
{
    public static PostAuthorizationSubject Anonymous { get; } =
        new(null, false, Array.Empty<string>());

    public bool IsInRole(string role) =>
        Roles.Any(value => string.Equals(value, role, StringComparison.OrdinalIgnoreCase));
}

public sealed record PostAuthorizationDecision(
    bool Exists,
    bool IsAuthorized,
    Guid PostId,
    Guid? AuthorId,
    PostStatus Status)
{
    public static PostAuthorizationDecision NotFound(Guid postId) =>
        new(false, false, postId, null, default);
}
