using System.IO.Compression;
using Microsoft.AspNetCore.ResponseCompression;

namespace BlogApp.Server.Api.Extensions;

public static class CachingExtensions
{
    public static IServiceCollection AddOutputCachePolicies(this IServiceCollection services)
    {
        services.AddOutputCache(options =>
        {
            // Default policy: 60 seconds
            options.AddBasePolicy(policy => policy.Expire(TimeSpan.FromSeconds(60)));

            // Short cache for lists (affected by new posts)
            options.AddPolicy("PostsList", policy =>
                policy.Expire(TimeSpan.FromMinutes(1))
                      .Tag("posts"));

            // Medium cache for individual posts
            options.AddPolicy("PostDetail", policy =>
                policy.Expire(TimeSpan.FromMinutes(5))
                      .SetVaryByRouteValue("slug", "id")
                      .Tag("posts"));

            // Longer cache for static-ish content
            options.AddPolicy("Categories", policy =>
                policy.Expire(TimeSpan.FromMinutes(10))
                      .Tag("categories"));

            options.AddPolicy("Tags", policy =>
                policy.Expire(TimeSpan.FromMinutes(10))
                      .Tag("tags"));
        });

        return services;
    }

    public static IServiceCollection AddResponseCompressionServices(this IServiceCollection services)
    {
        services.AddResponseCompression(options =>
        {
            options.EnableForHttps = true;
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
