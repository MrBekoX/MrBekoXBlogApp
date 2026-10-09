using BlogApp.Core.Application.Common.Models;
using Microsoft.AspNetCore.Antiforgery;

namespace BlogApp.Presentation.Api.Filters;

internal static class AntiforgeryExtensions
{
    public static TBuilder ValidateAntiforgery<TBuilder>(this TBuilder builder)
        where TBuilder : IEndpointConventionBuilder
    {
        return builder.AddEndpointFilter(async (context, next) =>
        {
            try
            {
                var antiforgery = context.HttpContext.RequestServices
                    .GetRequiredService<IAntiforgery>();
                await antiforgery.ValidateRequestAsync(context.HttpContext);
            }
            catch (AntiforgeryValidationException)
            {
                return Results.BadRequest(
                    ApiResponse<object>.FailureResult("Antiforgery token validation failed."));
            }

            return await next(context);
        });
    }
}
