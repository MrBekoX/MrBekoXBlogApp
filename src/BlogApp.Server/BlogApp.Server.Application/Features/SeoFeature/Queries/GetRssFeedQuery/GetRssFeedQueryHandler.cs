using System.ServiceModel.Syndication;
using System.Text;
using System.Xml;
using BlogApp.Server.Application.Common.Interfaces.Data;
using BlogApp.Server.Domain.Enums;
using MediatR;
using Microsoft.EntityFrameworkCore;

namespace BlogApp.Server.Application.Features.SeoFeature.Queries.GetRssFeedQuery;

public class GetRssFeedQueryHandler(
    IApplicationDbContext context) : IRequestHandler<GetRssFeedQueryRequest, GetRssFeedQueryResponse>
{
    public async Task<GetRssFeedQueryResponse> Handle(GetRssFeedQueryRequest request, CancellationToken cancellationToken)
    {
        var baseUrl = request.BaseUrl;

        var posts = await context.Posts
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
        feed.Copyright = new TextSyndicationContent($"\u00a9 {DateTime.UtcNow.Year} BlogApp");

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

        return new GetRssFeedQueryResponse
        {
            RssXml = Encoding.UTF8.GetString(stream.ToArray())
        };
    }
}
