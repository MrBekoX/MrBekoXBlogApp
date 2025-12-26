using System.ServiceModel.Syndication;
using System.Text;
using System.Xml;
using System.Xml.Linq;
using BlogApp.Server.Application.Common.Interfaces;
using BlogApp.Server.Domain.Enums;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;

namespace BlogApp.Server.Api.Controllers;

/// <summary>
/// SEO related endpoints (sitemap, robots.txt, RSS)
/// </summary>
[ApiController]
public class SeoController : ControllerBase
{
    private readonly IApplicationDbContext _context;
    private readonly IConfiguration _configuration;

    public SeoController(IApplicationDbContext context, IConfiguration configuration)
    {
        _context = context;
        _configuration = configuration;
    }

    private string GetBaseUrl()
    {
        var corsOrigins = _configuration.GetSection("CorsOrigins").Get<string[]>();
        return corsOrigins?.FirstOrDefault() ?? "http://localhost:3000";
    }

    /// <summary>
    /// Generate sitemap.xml
    /// </summary>
    [HttpGet("/sitemap.xml")]
    [Produces("application/xml")]
    [ResponseCache(Duration = 3600)] // 1 hour cache
    public async Task<IActionResult> Sitemap()
    {
        var baseUrl = GetBaseUrl();
        
        var posts = await _context.Posts
            .Where(p => p.Status == PostStatus.Published && !p.IsDeleted)
            .OrderByDescending(p => p.PublishedAt)
            .Select(p => new { p.Slug, p.UpdatedAt, p.PublishedAt })
            .ToListAsync();

        var categories = await _context.Categories
            .Where(c => !c.IsDeleted)
            .Select(c => new { c.Slug, c.UpdatedAt })
            .ToListAsync();

        XNamespace ns = "http://www.sitemaps.org/schemas/sitemap/0.9";

        var sitemap = new XDocument(
            new XDeclaration("1.0", "UTF-8", null),
            new XElement(ns + "urlset",
                // Homepage
                new XElement(ns + "url",
                    new XElement(ns + "loc", baseUrl),
                    new XElement(ns + "changefreq", "daily"),
                    new XElement(ns + "priority", "1.0")
                ),
                // Blog page
                new XElement(ns + "url",
                    new XElement(ns + "loc", $"{baseUrl}/posts"),
                    new XElement(ns + "changefreq", "daily"),
                    new XElement(ns + "priority", "0.9")
                ),
                // Posts
                posts.Select(p => new XElement(ns + "url",
                    new XElement(ns + "loc", $"{baseUrl}/posts/{p.Slug}"),
                    new XElement(ns + "lastmod", (p.UpdatedAt ?? p.PublishedAt ?? DateTime.UtcNow).ToString("yyyy-MM-dd")),
                    new XElement(ns + "changefreq", "weekly"),
                    new XElement(ns + "priority", "0.8")
                )),
                // Categories
                categories.Select(c => new XElement(ns + "url",
                    new XElement(ns + "loc", $"{baseUrl}/category/{c.Slug}"),
                    new XElement(ns + "lastmod", (c.UpdatedAt ?? DateTime.UtcNow).ToString("yyyy-MM-dd")),
                    new XElement(ns + "changefreq", "weekly"),
                    new XElement(ns + "priority", "0.6")
                ))
            )
        );

        return Content(sitemap.ToString(), "application/xml", Encoding.UTF8);
    }

    /// <summary>
    /// Generate robots.txt
    /// </summary>
    [HttpGet("/robots.txt")]
    [Produces("text/plain")]
    [ResponseCache(Duration = 86400)] // 24 hour cache
    public IActionResult Robots()
    {
        var baseUrl = GetBaseUrl();
        
        var robotsTxt = $@"User-agent: *
Allow: /

# Sitemap
Sitemap: {baseUrl}/sitemap.xml

# Disallow admin and API paths
Disallow: /admin/
Disallow: /api/
Disallow: /swagger/
Disallow: /login
Disallow: /register

# Allow search engines to index blog posts
Allow: /posts/
Allow: /category/
Allow: /tag/
";

        return Content(robotsTxt, "text/plain", Encoding.UTF8);
    }

    /// <summary>
    /// Generate RSS feed
    /// </summary>
    [HttpGet("/rss")]
    [HttpGet("/feed")]
    [HttpGet("/feed.xml")]
    [Produces("application/rss+xml")]
    [ResponseCache(Duration = 1800)] // 30 min cache
    public async Task<IActionResult> Rss()
    {
        var baseUrl = GetBaseUrl();
        
        var posts = await _context.Posts
            .Where(p => p.Status == PostStatus.Published && !p.IsDeleted)
            .OrderByDescending(p => p.PublishedAt)
            .Take(20)
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
            .ToListAsync();

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
                p.MetaDescription ?? p.Excerpt ?? (p.Content != null ? p.Content.Substring(0, Math.Min(200, p.Content.Length)) : ""),
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

        return File(stream.ToArray(), "application/rss+xml; charset=utf-8");
    }
}

