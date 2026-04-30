using System.ServiceModel.Syndication;
using System.Text;
using System.Xml;
using System.Xml.Linq;
using BlogApp.Server.Application.Common.Interfaces.Data;
using BlogApp.Server.Application.Common.Interfaces.Services;
using BlogApp.Server.Application.Common.Options;
using BlogApp.Server.Domain.Enums;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Options;

namespace BlogApp.Server.Api.Endpoints;

public static class SeoEndpoints
{
    public static IEndpointRouteBuilder RegisterSeoEndpoints(this IEndpointRouteBuilder app)
    {
        // GET /sitemap.xml
        app.MapGet("/sitemap.xml", async (
            IApplicationDbContext context,
            IOptions<SiteSettings> siteSettings,
            CancellationToken cancellationToken) =>
        {
            var baseUrl = siteSettings.Value.BaseUrl;

            var posts = await context.Posts
                .Where(p => p.Status == PostStatus.Published && !p.IsDeleted)
                .OrderByDescending(p => p.PublishedAt)
                .Select(p => new { p.Slug, p.UpdatedAt, p.PublishedAt })
                .ToListAsync(cancellationToken);

            var categories = await context.Categories
                .Where(c => !c.IsDeleted)
                .Select(c => new { c.Slug, c.UpdatedAt })
                .ToListAsync(cancellationToken);

            XNamespace ns = "http://www.sitemaps.org/schemas/sitemap/0.9";

            var sitemap = new XDocument(
                new XDeclaration("1.0", "UTF-8", null),
                new XElement(ns + "urlset",
                    new XElement(ns + "url",
                        new XElement(ns + "loc", baseUrl),
                        new XElement(ns + "changefreq", "daily"),
                        new XElement(ns + "priority", "1.0")
                    ),
                    new XElement(ns + "url",
                        new XElement(ns + "loc", $"{baseUrl}/posts"),
                        new XElement(ns + "changefreq", "daily"),
                        new XElement(ns + "priority", "0.9")
                    ),
                    posts.Select(p => new XElement(ns + "url",
                        new XElement(ns + "loc", $"{baseUrl}/posts/{p.Slug}"),
                        new XElement(ns + "lastmod", (p.UpdatedAt ?? p.PublishedAt ?? DateTime.UtcNow).ToString("yyyy-MM-dd")),
                        new XElement(ns + "changefreq", "weekly"),
                        new XElement(ns + "priority", "0.8")
                    )),
                    categories.Select(c => new XElement(ns + "url",
                        new XElement(ns + "loc", $"{baseUrl}/category/{c.Slug}"),
                        new XElement(ns + "lastmod", (c.UpdatedAt ?? DateTime.UtcNow).ToString("yyyy-MM-dd")),
                        new XElement(ns + "changefreq", "weekly"),
                        new XElement(ns + "priority", "0.6")
                    ))
                )
            );

            return Results.Content(sitemap.ToString(), "application/xml", Encoding.UTF8);
        })
        .WithName("Sitemap")
        .WithDescription("Generate sitemap.xml")
        .WithTags("SEO")
        .CacheOutput("SitemapCache")
        .Produces<string>(200, "application/xml");

        // GET /robots.txt
        app.MapGet("/robots.txt", (IOptions<SiteSettings> siteSettings) =>
        {
            var baseUrl = siteSettings.Value.BaseUrl;

            var robotsTxt = $@"User-agent: *
Allow: /
Disallow: /admin/
Disallow: /api/
Disallow: /swagger/
Disallow: /login
Disallow: /register

# AI Search Crawlers — explicit allow
User-agent: GPTBot
Allow: /
Disallow: /admin/
Disallow: /api/

User-agent: OAI-SearchBot
Allow: /
Disallow: /admin/
Disallow: /api/

User-agent: ChatGPT-User
Allow: /
Disallow: /admin/
Disallow: /api/

User-agent: ClaudeBot
Allow: /
Disallow: /admin/
Disallow: /api/

User-agent: Claude-SearchBot
Allow: /
Disallow: /admin/
Disallow: /api/

User-agent: PerplexityBot
Allow: /
Disallow: /admin/
Disallow: /api/

User-agent: Google-Extended
Allow: /
Disallow: /admin/
Disallow: /api/

User-agent: Bingbot
Allow: /
Disallow: /admin/
Disallow: /api/

# Sitemap
Sitemap: {baseUrl}/sitemap.xml
";

            return Results.Content(robotsTxt, "text/plain", Encoding.UTF8);
        })
        .WithName("Robots")
        .WithDescription("Generate robots.txt")
        .WithTags("SEO")
        .CacheOutput("RobotsCache")
        .Produces<string>(200, "text/plain");

        // GET /llms.txt — AI model'lerin siteyi anlamasi icin yapilandirilmis Markdown
        app.MapGet("/llms.txt", async (
            IApplicationDbContext context,
            IOptions<SiteSettings> siteSettings,
            IOptions<ServerLimitsSettings> serverLimits,
            CancellationToken cancellationToken) =>
        {
            var baseUrl = siteSettings.Value.BaseUrl;

            var maxPosts = serverLimits.Value.LlmsTxtMaxPosts;
            var posts = await context.Posts
                .Where(p => p.Status == PostStatus.Published && !p.IsDeleted)
                .OrderByDescending(p => p.PublishedAt)
                .Take(maxPosts)
                .Select(p => new
                {
                    p.Title,
                    p.Slug,
                    Excerpt = p.Excerpt ?? (p.Content.Length > 150 ? p.Content.Substring(0, 150) + "..." : p.Content),
                    p.PublishedAt
                })
                .ToListAsync(cancellationToken);

            var sb = new StringBuilder();
            sb.AppendLine("# MrBekoX Dev Blog");
            sb.AppendLine();
            sb.AppendLine("> Personal tech blog by Berkay Kaplan covering .NET, React, Next.js, Python, AI, software architecture, and system design.");
            sb.AppendLine();
            sb.AppendLine("## Blog Posts");
            sb.AppendLine();

            foreach (var post in posts)
            {
                var date = post.PublishedAt?.ToString("yyyy-MM-dd") ?? "";
                sb.AppendLine($"- [{post.Title}]({baseUrl}/posts/{post.Slug}): {post.Excerpt} ({date})");
            }

            sb.AppendLine();
            sb.AppendLine("## Links");
            sb.AppendLine();
            sb.AppendLine($"- [Blog]({baseUrl}): Ana sayfa");
            sb.AppendLine($"- [RSS Feed]({baseUrl}/rss): RSS 2.0 feed");
            sb.AppendLine($"- [Sitemap]({baseUrl}/sitemap.xml): XML sitemap");

            return Results.Content(sb.ToString(), "text/plain", Encoding.UTF8);
        })
        .WithName("LlmsTxt")
        .WithDescription("Generate llms.txt for AI models")
        .WithTags("SEO")
        .CacheOutput("LlmsTxtCache")
        .Produces<string>(200, "text/plain");

        // GET /rss, /feed, /feed.xml
        app.MapGet("/rss", RssHandler)
            .WithName("RssFeed")
            .WithDescription("Generate RSS feed")
            .WithTags("SEO")
            .CacheOutput("RssFeedCache")
            .Produces<byte[]>(200, "application/rss+xml");

        app.MapGet("/feed", RssHandler)
            .WithName("Feed")
            .WithTags("SEO")
            .CacheOutput("RssFeedCache")
            .Produces<byte[]>(200, "application/rss+xml");

        app.MapGet("/feed.xml", RssHandler)
            .WithName("FeedXml")
            .WithTags("SEO")
            .CacheOutput("RssFeedCache")
            .Produces<byte[]>(200, "application/rss+xml");

        return app;
    }

    private static async Task<IResult> RssHandler(
        IApplicationDbContext context,
        IOptions<SiteSettings> siteSettings,
        IOptions<ServerLimitsSettings> serverLimits,
        CancellationToken cancellationToken)
    {
        var baseUrl = siteSettings.Value.BaseUrl;

        var posts = await context.Posts
            .Where(p => p.Status == PostStatus.Published && !p.IsDeleted)
            .OrderByDescending(p => p.PublishedAt)
            .Take(serverLimits.Value.RssFeedMaxPosts)
            .Include(p => p.Author)
            .Include(p => p.Category)
            .Select(p => new
            {
                p.Title,
                p.Slug,
                p.Excerpt,
                p.Content,
                p.PublishedAt,
                p.FeaturedImageUrl,
                p.MetaDescription,
                AuthorName = p.Author.FullName,
                CategoryName = p.Category != null ? p.Category.Name : null
            })
            .ToListAsync(cancellationToken);

        var feed = new SyndicationFeed(
            "BlogApp",
            "Latest blog posts",
            new Uri(baseUrl),
            "BlogAppRSS",
            posts.FirstOrDefault()?.PublishedAt ?? DateTime.UtcNow
        );

        feed.Authors.Add(new SyndicationPerson { Name = "BlogApp" });
        feed.Language = "tr-TR";
        feed.Copyright = new TextSyndicationContent($"© {DateTime.UtcNow.Year} BlogApp");

        var items = posts.Select(p =>
        {
            var item = new SyndicationItem(
                p.Title,
                p.MetaDescription ?? p.Excerpt ?? (p.Content != null ? System.Security.SecurityElement.Escape(p.Content.Substring(0, Math.Min(200, p.Content.Length))) : ""),
                new Uri($"{baseUrl}/posts/{p.Slug}"),
                p.Slug,
                p.PublishedAt ?? DateTime.UtcNow
            );

            if (!string.IsNullOrEmpty(p.AuthorName))
                item.Authors.Add(new SyndicationPerson { Name = p.AuthorName });

            if (!string.IsNullOrEmpty(p.CategoryName))
                item.Categories.Add(new SyndicationCategory(p.CategoryName));

            return item;
        }).ToList();

        feed.Items = items;

        var settings = new XmlWriterSettings
        {
            Encoding = Encoding.UTF8,
            NewLineHandling = NewLineHandling.Entitize,
            Indent = true,
            Async = true
        };

        using var stream = new MemoryStream();
        await using (var xmlWriter = XmlWriter.Create(stream, settings))
        {
            var rssFormatter = new Rss20FeedFormatter(feed, false);
            rssFormatter.WriteTo(xmlWriter);
            await xmlWriter.FlushAsync();
        }

        return Results.File(stream.ToArray(), "application/rss+xml; charset=utf-8");
    }
}
