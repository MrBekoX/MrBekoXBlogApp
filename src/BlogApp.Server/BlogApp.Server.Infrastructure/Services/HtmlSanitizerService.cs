using BlogApp.Server.Application.Common.Interfaces.Services;
using Ganss.Xss;

namespace BlogApp.Server.Infrastructure.Services;

public class HtmlSanitizerService : IHtmlSanitizerService
{
    private readonly HtmlSanitizer _sanitizer;

    public HtmlSanitizerService()
    {
        _sanitizer = new HtmlSanitizer();
        // Allow common blog formatting tags
        _sanitizer.AllowedTags.Add("h1");
        _sanitizer.AllowedTags.Add("h2");
        _sanitizer.AllowedTags.Add("h3");
        _sanitizer.AllowedTags.Add("h4");
        _sanitizer.AllowedTags.Add("h5");
        _sanitizer.AllowedTags.Add("h6");
        _sanitizer.AllowedTags.Add("pre");
        _sanitizer.AllowedTags.Add("code");
        _sanitizer.AllowedTags.Add("blockquote");
        _sanitizer.AllowedTags.Add("table");
        _sanitizer.AllowedTags.Add("thead");
        _sanitizer.AllowedTags.Add("tbody");
        _sanitizer.AllowedTags.Add("tr");
        _sanitizer.AllowedTags.Add("th");
        _sanitizer.AllowedTags.Add("td");
        // Remove dangerous attributes
        _sanitizer.AllowedAttributes.Remove("onerror");
        _sanitizer.AllowedAttributes.Remove("onload");
    }

    public string? Sanitize(string? html)
    {
        return string.IsNullOrEmpty(html) ? html : _sanitizer.Sanitize(html);
    }
}
