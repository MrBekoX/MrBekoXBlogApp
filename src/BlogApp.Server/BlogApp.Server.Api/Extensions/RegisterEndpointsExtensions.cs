using BlogApp.Server.Api.Endpoints;

namespace BlogApp.Server.Api.Extensions;

public static class RegisterEndpointsExtensions
{
    public static IEndpointRouteBuilder RegisterAllEndpoints(this IEndpointRouteBuilder app)
    {
        // API Endpoints
        app.RegisterAuthEndpoints();
        app.RegisterCategoriesEndpoints();
        app.RegisterPostsEndpoints();
        app.RegisterTagsEndpoints();
        app.RegisterMediaEndpoints();
        app.RegisterCsrfEndpoints();

        // SEO Endpoints (root paths: /sitemap.xml, /robots.txt, /rss, /feed)
        app.RegisterSeoEndpoints();

        return app;
    }
}
