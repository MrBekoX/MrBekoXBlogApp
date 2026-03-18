using BlogApp.Server.Api.Endpoints;

namespace BlogApp.Server.Api.Extensions;

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
        app.RegisterAiEndpoints();
        app.RegisterChatEndpoints();
        app.RegisterInternalSecurityEndpoints();
        app.RegisterAdminEndpoints();

        app.RegisterSeoEndpoints();

        return app;
    }
}
