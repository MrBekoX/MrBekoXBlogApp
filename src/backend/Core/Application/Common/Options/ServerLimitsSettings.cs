namespace BlogApp.Core.Application.Common.Options;

/// <summary>
/// Kestrel, FormOptions ve SignalR limitleri — appsettings.json "ServerLimits" section
/// </summary>
public sealed class ServerLimitsSettings
{
    public const string SectionName = "ServerLimits";

    // Kestrel
    public long MaxRequestBodySizeBytes { get; set; } = 50_000_000; // 50 MB

    // FormOptions
    public long MultipartBodyLengthLimit { get; set; } = 50_000_000; // 50 MB
    public int FormValueLengthLimit { get; set; } = 4_194_304; // 4 MB
    public int MultipartHeadersLengthLimit { get; set; } = 65_536; // 64 KB

    // SignalR
    public int SignalRKeepAliveIntervalSeconds { get; set; } = 10;
    public int SignalRClientTimeoutSeconds { get; set; } = 30;
    public int SignalRHandshakeTimeoutSeconds { get; set; } = 15;

    // Output Cache TTLs (minutes)
    public int CategoriesCacheMinutes { get; set; } = 10;
    public int TagsCacheMinutes { get; set; } = 10;

    // SEO cache TTLs (minutes). RobotsCacheMinutes is applied.
    // Sitemap, llms.txt and RSS ignore their minute settings and are served uncached.
    public int SitemapCacheMinutes { get; set; } = 60;
    public int RobotsCacheMinutes { get; set; } = 1440; // 24h
    public int LlmsTxtCacheMinutes { get; set; } = 360; // retained so existing config still binds
    public int RssFeedCacheMinutes { get; set; } = 30;

    // SEO Content Limits
    public int RssFeedMaxPosts { get; set; } = 20;
    public int LlmsTxtMaxPosts { get; set; } = 50;
}
