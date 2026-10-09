using BlogApp.Presentation.Api.Endpoints;

namespace BlogApp.Presentation.Api.Extensions;

public static class RegisterEndpointsExtensions
{
    public static IEndpointRouteBuilder RegisterAllEndpoints(this IEndpointRouteBuilder app)
    {
        app.RegisterAuthEndpoints();
        app.RegisterCategoriesEndpoints();
        app.RegisterPostsEndpoints();
        app.RegisterTagsEndpoints();
        app.RegisterMediaEndpoints();
        app.RegisterCsrfEndpoints();

        app.RegisterSeoEndpoints();

        return app;
    }
}
