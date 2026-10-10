using System.ServiceModel.Syndication;
using System.Text;
using System.Xml;
using BlogApp.Core.Application.Common.Interfaces.Data;
using BlogApp.Core.Application.Common.Options;
using BlogApp.Core.Domain.Enums;
using BlogApp.Presentation.Api.Seo;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Options;

namespace BlogApp.Presentation.Api.Endpoints;

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
            var posts = await context.Posts
                .Where(p => p.Status == PostStatus.Published && !p.IsDeleted)
                .OrderByDescending(p => p.PublishedAt)
                .Select(p => new { p.Slug, p.UpdatedAt, p.PublishedAt })
                .ToListAsync(cancellationToken);

            var sitemap = SeoDocuments.BuildSitemapXml(
                siteSettings.Value.BaseUrl,
                posts.Select(p => new SeoSitemapPost(p.Slug, p.UpdatedAt, p.PublishedAt)));

            return Results.Content(sitemap, "application/xml", Encoding.UTF8);
        })
        .WithName("Sitemap")
        .WithDescription("Generate sitemap.xml")
        .WithTags("SEO")
        .Produces<string>(200, "application/xml");

        // GET /robots.txt
        app.MapGet("/robots.txt", (IOptions<SiteSettings> siteSettings) =>
        {
            var baseUrl = SeoDocuments.NormalizeBaseUrl(siteSettings.Value.BaseUrl);

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
            var maxPosts = serverLimits.Value.LlmsTxtMaxPosts;
            var posts = await context.Posts
                .Where(p => p.Status == PostStatus.Published && !p.IsDeleted)
                .OrderByDescending(p => p.PublishedAt)
                .Take(maxPosts)
                .Select(p => new
                {
                    p.Title,
                    p.Slug,
                    p.Excerpt,
                    Content = p.Content.Length > 2000 ? p.Content.Substring(0, 2000) : p.Content,
                    p.PublishedAt
                })
                .ToListAsync(cancellationToken);

            var llmsTxt = SeoDocuments.BuildLlmsTxt(
                siteSettings.Value.BaseUrl,
                posts.Select(p => new SeoPostLink(p.Title, p.Slug, p.Excerpt, p.Content, p.PublishedAt)));

            return Results.Content(llmsTxt, "text/plain", Encoding.UTF8);
        })
        .WithName("LlmsTxt")
        .WithDescription("Generate llms.txt for AI models")
        .WithTags("SEO")
        .Produces<string>(200, "text/plain");

        // GET /rss, /feed, /feed.xml
        app.MapGet("/rss", RssHandler)
            .WithName("RssFeed")
            .WithDescription("Generate RSS feed")
            .WithTags("SEO")
            .Produces<byte[]>(200, "application/rss+xml");

        app.MapGet("/feed", RssHandler)
            .WithName("Feed")
            .WithTags("SEO")
            .Produces<byte[]>(200, "application/rss+xml");

        app.MapGet("/feed.xml", RssHandler)
            .WithName("FeedXml")
            .WithTags("SEO")
            .Produces<byte[]>(200, "application/rss+xml");

        return app;
    }

    private static async Task<IResult> RssHandler(
        IApplicationDbContext context,
        IOptions<SiteSettings> siteSettings,
        IOptions<ServerLimitsSettings> serverLimits,
        CancellationToken cancellationToken)
    {
        var baseUrl = SeoDocuments.NormalizeBaseUrl(siteSettings.Value.BaseUrl);

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
                Content = p.Content.Length > 2000 ? p.Content.Substring(0, 2000) : p.Content,
                p.PublishedAt,
                p.MetaDescription,
                AuthorName = p.Author.FullName,
                CategoryName = p.Category != null ? p.Category.Name : null
            })
            .ToListAsync(cancellationToken);

        var feed = new SyndicationFeed(
            SeoDocuments.SiteName,
            SeoDocuments.SiteDescription,
            new Uri(baseUrl),
            SeoDocuments.SiteName,
            posts.FirstOrDefault()?.PublishedAt ?? DateTime.UtcNow
        );

        feed.Authors.Add(new SyndicationPerson { Name = SeoDocuments.AuthorName });
        feed.Language = "tr-TR";
        feed.Copyright = new TextSyndicationContent($"© {DateTime.UtcNow.Year} {SeoDocuments.SiteName}");

        var items = posts.Select(p =>
        {
            var item = new SyndicationItem(
                p.Title,
                SeoDocuments.PlainExcerpt(p.MetaDescription ?? p.Excerpt, p.Content, 200),
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
