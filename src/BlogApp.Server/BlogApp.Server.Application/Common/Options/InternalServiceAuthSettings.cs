namespace BlogApp.Server.Application.Common.Options;

public sealed class InternalServiceAuthSettings
{
    public const string SectionName = "InternalServiceAuth";

    public string HeaderName { get; init; } = "X-Service-Key";
    public string ServiceKey { get; init; } = string.Empty;
}
