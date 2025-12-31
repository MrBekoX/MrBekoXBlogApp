namespace BlogApp.Server.Application.Common.Options;

/// <summary>
/// Site configuration settings (CORS origins, base URL, etc.)
/// </summary>
public sealed class SiteSettings
{
    public const string SectionName = "CorsOrigins";

    public string[] Origins { get; set; } = ["http://localhost:3000"];

    public string BaseUrl => Origins.FirstOrDefault() ?? "http://localhost:3000";
}

