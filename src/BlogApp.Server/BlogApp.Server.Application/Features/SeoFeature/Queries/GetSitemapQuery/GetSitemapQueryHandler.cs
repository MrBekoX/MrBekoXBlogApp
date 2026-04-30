using System.Xml.Linq;
using BlogApp.Server.Application.Common.Interfaces.Data;
using BlogApp.Server.Domain.Enums;
using MediatR;
using Microsoft.EntityFrameworkCore;

namespace BlogApp.Server.Application.Features.SeoFeature.Queries.GetSitemapQuery;

public class GetSitemapQueryHandler(
    IApplicationDbContext context) : IRequestHandler<GetSitemapQueryRequest, GetSitemapQueryResponse>
{
    public async Task<GetSitemapQueryResponse> Handle(GetSitemapQueryRequest request, CancellationToken cancellationToken)
    {
        var baseUrl = request.BaseUrl;

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

        return new GetSitemapQueryResponse
        {
            XmlContent = sitemap.ToString()
        };
    }
}
