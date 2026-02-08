namespace BlogApp.Server.Application.Common.Interfaces.Services;

public interface IHtmlSanitizerService
{
    string? Sanitize(string? html);
}
