namespace BlogApp.Server.Application.Common.Options;

public sealed class ChatSessionTokenSettings
{
    public const string SectionName = "ChatSessionTokens";

    public int ExpirationMinutes { get; init; } = 15;
}
