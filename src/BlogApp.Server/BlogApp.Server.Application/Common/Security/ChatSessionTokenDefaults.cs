namespace BlogApp.Server.Application.Common.Security;

public static class ChatSessionTokenDefaults
{
    public const string SchemeName = "ChatSession";
    public const string Issuer = "BlogApp.ChatSession";
    public const string Audience = "BlogApp.ChatSession";

    public const string TokenUseClaim = "token_use";
    public const string TokenUseValue = "chat_session";
    public const string SessionIdClaim = "chat_session_id";
    public const string PostIdClaim = "chat_post_id";
    public const string OperationIdClaim = "chat_operation_id";
    public const string CorrelationIdClaim = "chat_correlation_id";
    public const string FingerprintClaim = "chat_fingerprint";
}
