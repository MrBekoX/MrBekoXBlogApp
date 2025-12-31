namespace BlogApp.Server.Application.Common.Options;

/// <summary>
/// JWT authentication configuration settings
/// </summary>
public sealed class JwtSettings
{
    public const string SectionName = "JwtSettings";

    public string Secret { get; init; } = string.Empty;
    public string Issuer { get; init; } = "BlogApp";
    public string Audience { get; init; } = "BlogApp";
    public int ExpirationMinutes { get; init; } = 60;
}

