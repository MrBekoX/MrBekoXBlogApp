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

    // Forwarded Headers
    public int ForwardedHeadersForwardLimit { get; set; } = 2; // ALB + nginx = 2 proxy hop

    // Output Cache TTLs (minutes)
    public int CategoriesCacheMinutes { get; set; } = 10;
    public int TagsCacheMinutes { get; set; } = 10;

    // SEO Cache TTLs (minutes)
    public int SitemapCacheMinutes { get; set; } = 60;
    public int RobotsCacheMinutes { get; set; } = 1440; // 24h
    public int LlmsTxtCacheMinutes { get; set; } = 360; // 6h
    public int RssFeedCacheMinutes { get; set; } = 30;

    // SEO Content Limits
    public int RssFeedMaxPosts { get; set; } = 20;
    public int LlmsTxtMaxPosts { get; set; } = 50;
}
