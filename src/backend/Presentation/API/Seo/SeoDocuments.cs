using System.Text;
using System.Text.RegularExpressions;
using System.Xml.Linq;

namespace BlogApp.Presentation.Api.Seo;

public sealed record SeoSitemapPost(string Slug, DateTime? UpdatedAt, DateTime? PublishedAt);

public sealed record SeoPostLink(
    string Title,
    string Slug,
    string? Excerpt,
    string? Content,
    DateTime? PublishedAt);

public static class SeoDocuments
{
    public const string SiteName = "MrBekoX";
    public const string AuthorName = "Sample Author";
    public const string SiteDescription =
        "Yazılım geliştirme yolculuğumda öğrendiklerimi, aldığım teknik notları ve proje deneyimlerimi paylaştığım kişisel blog.";

    public static string NormalizeBaseUrl(string? baseUrl)
    {
        if (string.IsNullOrWhiteSpace(baseUrl))
            return "http://localhost:3000";

        return baseUrl.Trim().TrimEnd('/');
    }

    public static string PlainExcerpt(string? excerpt, string? content, int maxLength = 150)
    {
        var source = string.IsNullOrWhiteSpace(excerpt) ? content : excerpt;
        if (string.IsNullOrWhiteSpace(source) || maxLength <= 0)
            return string.Empty;

        var plain = Regex.Replace(StripMarkdown(source), @"\s+", " ").Trim();
        if (plain.Length <= maxLength)
            return plain;

        if (maxLength <= 3)
            return plain[..maxLength];

        return plain[..(maxLength - 3)].TrimEnd() + "...";
    }

    public static string MarkdownLabel(string? value)
    {
        if (string.IsNullOrWhiteSpace(value))
            return "Yazı";

        var label = Regex.Replace(value, @"\s+", " ").Trim()
            .Replace("[", "(", StringComparison.Ordinal)
            .Replace("]", ")", StringComparison.Ordinal);

        return label.Length <= 180 ? label : label[..177].TrimEnd() + "...";
    }

    public static string BuildSitemapXml(string? baseUrl, IEnumerable<SeoSitemapPost> posts)
    {
        var origin = NormalizeBaseUrl(baseUrl);
        XNamespace ns = "http://www.sitemaps.org/schemas/sitemap/0.9";
        var urlset = new XElement(ns + "urlset",
            SitemapUrl(ns, origin, "daily", "1.0", null),
            SitemapUrl(ns, $"{origin}/posts", "daily", "0.9", null));

        foreach (var post in posts)
        {
            if (string.IsNullOrWhiteSpace(post.Slug))
                continue;

            urlset.Add(SitemapUrl(
                ns,
                $"{origin}/posts/{post.Slug}",
                "weekly",
                "0.8",
                post.UpdatedAt ?? post.PublishedAt));
        }

        return new XDocument(urlset).ToString();
    }

    public static string BuildLlmsTxt(string? baseUrl, IEnumerable<SeoPostLink> posts)
    {
        var origin = NormalizeBaseUrl(baseUrl);
        var sb = new StringBuilder();
        sb.AppendLine($"# {SiteName}");
        sb.AppendLine();
        sb.AppendLine($"> {SiteDescription}");
        sb.AppendLine();
        sb.AppendLine("## Blog Posts");
        sb.AppendLine();

        foreach (var post in posts)
        {
            if (string.IsNullOrWhiteSpace(post.Slug))
                continue;

            var note = PlainExcerpt(post.Excerpt, post.Content);
            var date = post.PublishedAt?.ToString("yyyy-MM-dd");
            var suffix = string.IsNullOrEmpty(note) ? string.Empty : $": {note}";
            if (!string.IsNullOrEmpty(date))
                suffix = string.IsNullOrEmpty(suffix) ? $": {date}" : $"{suffix} ({date})";

            sb.AppendLine($"- [{MarkdownLabel(post.Title)}]({origin}/posts/{post.Slug}){suffix}");
        }

        sb.AppendLine();
        sb.AppendLine("## Links");
        sb.AppendLine();
        sb.AppendLine($"- [Blog]({origin}): Ana sayfa");
        sb.AppendLine($"- [RSS Feed]({origin}/rss): RSS 2.0 feed");
        sb.AppendLine($"- [Sitemap]({origin}/sitemap.xml): XML sitemap");
        return sb.ToString();
    }

    private static XElement SitemapUrl(XNamespace ns, string loc, string changeFreq, string priority, DateTime? lastModified)
    {
        var url = new XElement(ns + "url",
            new XElement(ns + "loc", loc),
            new XElement(ns + "changefreq", changeFreq),
            new XElement(ns + "priority", priority));

        if (lastModified.HasValue)
            url.Add(new XElement(ns + "lastmod", lastModified.Value.ToString("yyyy-MM-dd")));

        return url;
    }

    private static string StripMarkdown(string value)
    {
        var text = Regex.Replace(value, @"```[\s\S]*?```", " ");
        text = Regex.Replace(text, @"`[^`]+`", " ");
        text = Regex.Replace(text, @"!\[[^\]]*\]\([^)]*\)", " ");
        text = Regex.Replace(text, @"\[([^\]]+)\]\([^)]*\)", "$1");
        text = Regex.Replace(text, @"^#{1,6}\s+", "", RegexOptions.Multiline);
        text = Regex.Replace(text, @"[*_~]+", "");
        text = Regex.Replace(text, @">\s+", "");
        text = Regex.Replace(text, @"^[-*]\s+", "", RegexOptions.Multiline);
        return text;
    }
}
