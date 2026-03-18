namespace BlogApp.Server.Application.Common.Options;

public sealed class ChatAbuseProtectionSettings
{
    public const string SectionName = "ChatAbuseProtection";

    public bool Enabled { get; init; } = true;
    public bool AllowMissingTurnstileInDevelopment { get; init; } = false;
    public bool AnonymousOnly { get; init; } = true;
    public int SoftRequestsPerMinute { get; init; } = 4;
    public int HardRequestsPerMinute { get; init; } = 12;
    public int SoftRequestsPerHour { get; init; } = 40;
    public int HardRequestsPerHour { get; init; } = 180;
    public int SoftEstimatedTokensPerDay { get; init; } = 60000;
    public int HardEstimatedTokensPerDay { get; init; } = 150000;
    public int TurnstileBypassMinutes { get; init; } = 20;
    public string TurnstileAction { get; init; } = "chat";
}

