using System.IO.Compression;
using BlogApp.Core.Application.Common.Options;
using Microsoft.AspNetCore.ResponseCompression;

namespace BlogApp.Presentation.Api.Extensions;

public static class CachingExtensions
{
    public static IServiceCollection AddOutputCachePolicies(this IServiceCollection services, IConfiguration configuration)
    {
        var limits = configuration.GetSection(ServerLimitsSettings.SectionName)
            .Get<ServerLimitsSettings>() ?? new ServerLimitsSettings();

        services.AddOutputCache(options =>
        {
            // NO base policy — only explicitly opted-in endpoints are output-cached.
            // Posts do NOT use Output Cache — SWR (CachingBehavior) handles caching with
            // reliable group-versioned invalidation via RotateGroupVersionAsync.
            // Output Cache's EvictByTagAsync proved unreliable for posts publish/unpublish.

            // Static-ish content — changes infrequently, no SWR layer
            options.AddPolicy("Categories", policy =>
                policy.Expire(TimeSpan.FromMinutes(limits.CategoriesCacheMinutes))
                      .Tag("categories"));

            options.AddPolicy("Tags", policy =>
                policy.Expire(TimeSpan.FromMinutes(limits.TagsCacheMinutes))
                      .Tag("tags"));

            // robots.txt is static copy. Sitemap, llms.txt and RSS are not output-cached:
            // EvictByTagAsync is unreliable after publish, and a long TTL served stale discovery files.
            options.AddPolicy("RobotsCache", policy =>
                policy.Expire(TimeSpan.FromMinutes(limits.RobotsCacheMinutes)));
        });

        return services;
    }

    public static IServiceCollection AddResponseCompressionServices(this IServiceCollection services)
    {
        services.AddResponseCompression(options =>
        {
            options.EnableForHttps = false;
            options.Providers.Add<BrotliCompressionProvider>();
            options.Providers.Add<GzipCompressionProvider>();
            options.MimeTypes = ResponseCompressionDefaults.MimeTypes.Concat(
                ["application/json", "text/plain", "text/html", "application/xml", "text/xml"]);
        });
        services.Configure<BrotliCompressionProviderOptions>(options => options.Level = CompressionLevel.Fastest);
        services.Configure<GzipCompressionProviderOptions>(options => options.Level = CompressionLevel.SmallestSize);

        return services;
    }
}
