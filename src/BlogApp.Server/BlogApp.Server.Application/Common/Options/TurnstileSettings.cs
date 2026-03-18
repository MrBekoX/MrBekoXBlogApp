namespace BlogApp.Server.Application.Common.Options;

public sealed class TurnstileSettings
{
    public const string SectionName = "Turnstile";

    public string SiteKey { get; init; } = string.Empty;
    public string SecretKey { get; init; } = string.Empty;
    public string VerifyUrl { get; init; } = "https://challenges.cloudflare.com/turnstile/v0/siteverify";
}
