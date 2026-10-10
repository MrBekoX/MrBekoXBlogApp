using BlogApp.Presentation.Api.Seo;
using Xunit;

namespace BlogApp.Presentation.Api.Tests;

public class SeoDocumentsTests
{
    [Fact]
    public void Sitemap_lists_real_post_urls_and_omits_missing_category_pages()
    {
        var xml = SeoDocuments.BuildSitemapXml("https://mrbekox.dev/",
        [
            new SeoSitemapPost("cqrs-nedir", new DateTime(2026, 1, 2), new DateTime(2026, 1, 1))
        ]);

        Assert.DoesNotContain("/category/", xml);
        Assert.Contains("https://mrbekox.dev/posts/cqrs-nedir", xml);
        Assert.Contains("2026-01-02", xml);
    }

    [Fact]
    public void Llms_follows_the_spec_and_keeps_excerpts_on_one_plain_line()
    {
        var text = SeoDocuments.BuildLlmsTxt("https://mrbekox.dev",
        [
            new SeoPostLink(
                "CQRS [v1]",
                "cqrs",
                null,
                "# Başlık\n\n**kalın** ve uzun bir açıklama metni burada yer alır.",
                new DateTime(2026, 3, 4))
        ]);

        Assert.StartsWith("# MrBekoX", text);
        Assert.Contains("> Yazılım geliştirme yolculuğumda", text);
        Assert.Contains("## Blog Posts", text);
        Assert.Contains("## Links", text);
        Assert.Contains("https://mrbekox.dev/rss", text);
        Assert.Contains("https://mrbekox.dev/sitemap.xml", text);

        var postLine = text.Split('\n').Single(line => line.Contains("/posts/cqrs", StringComparison.Ordinal));
        Assert.Contains("CQRS (v1)", postLine);
        Assert.DoesNotContain("**", postLine);
        Assert.DoesNotContain("# Başlık", postLine);
        Assert.DoesNotContain("\n", postLine);
    }
}
