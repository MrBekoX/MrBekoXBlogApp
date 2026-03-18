namespace BlogApp.Server.Application.Common.Interfaces.Services;

public interface IChatSessionTokenService
{
    ChatSessionTokenIssueResult IssueToken(ChatSessionTokenIssueRequest request);
}

public sealed record ChatSessionTokenIssueRequest(
    string SessionId,
    Guid PostId,
    string OperationId,
    string CorrelationId,
    string? Fingerprint);

public sealed record ChatSessionTokenIssueResult(string Token, DateTimeOffset ExpiresAt);
