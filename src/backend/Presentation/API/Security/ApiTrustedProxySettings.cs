namespace BlogApp.Presentation.Api.Security;

/// <summary>Exact Nginx peers allowed to supply the canonical client IP and scheme.</summary>
public sealed class ApiTrustedProxySettings
{
    public const string SectionName = "ForwardedHeaders";

    public bool Enabled { get; set; }

    public string[] KnownProxies { get; set; } = [];
}
