namespace BlogApp.Server.Application.Common.Interfaces.Services;

public interface IChatAbuseProtectionService
{
    Task<ChatAbuseDecision> AuthorizeAnonymousAsync(AnonymousChatRequest request, CancellationToken cancellationToken = default);
}

public sealed record AnonymousChatRequest(
    Guid PostId,
    string SessionId,
    string Message,
    int ConversationHistoryCount,
    string? ClientFingerprint,
    string? TurnstileToken,
    string? RemoteIpAddress);

public sealed record ChatAbuseDecision(
    bool Allowed,
    bool RequiresTurnstile,
    bool ServiceUnavailable,
    string Message,
    int? RetryAfterSeconds)
{
    public static ChatAbuseDecision Allow() => new(true, false, false, string.Empty, null);

    public static ChatAbuseDecision Challenge(string message, int retryAfterSeconds = 60) =>
        new(false, true, false, message, retryAfterSeconds);

    public static ChatAbuseDecision Deny(string message, int retryAfterSeconds = 300) =>
        new(false, false, false, message, retryAfterSeconds);

    public static ChatAbuseDecision Unavailable(string message) =>
        new(false, false, true, message, null);
}
