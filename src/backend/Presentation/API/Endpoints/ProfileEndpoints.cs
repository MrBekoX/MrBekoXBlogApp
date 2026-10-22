using BlogApp.Core.Application.Common.Models;
using BlogApp.Core.Application.Features.ProfileFeature.DTOs;
using BlogApp.Core.Application.Features.ProfileFeature.Queries.GetAuthorProfileQuery;
using BlogApp.Core.Application.Features.ProfileFeature.Queries.GetAuthorProfileSnapshotQuery;
using BlogApp.Presentation.Api.Helpers;
using MediatR;

namespace BlogApp.Presentation.Api.Endpoints;

/// <summary>
/// Public yazar profili (Who am I, K2/K6):
///   GET /api/v1/profile          — aktif + public + hash doğrulanmış canonical profil (/about kaynağı)
///   GET /api/v1/profile/snapshot — yalnız aktif sürüm metadatası (drift denetimi)
/// Kural: yanıtlar <c>Cache-Control: no-store</c> taşır ve output cache politikası YOKTUR — her istek
/// aktif sürüm/public politikasını yeniden uygular; geri çekilmiş/eski profil gövdesi cache'ten
/// sunulmaz (A37). Profil kullanılamıyorsa 503 + code <c>profile_unavailable</c>.
/// </summary>
public static class ProfileEndpoints
{
    public const string NoStore = "no-store";

    public static IEndpointRouteBuilder RegisterProfileEndpoints(this IEndpointRouteBuilder app)
    {
        var versionedGroup = app.NewVersionedApi("Profile");
        var group = versionedGroup.MapGroup("/api/v{version:apiVersion}/profile")
            .HasApiVersion(1.0)
            .WithTags("Profile");

        group.MapGet("/", async (
            HttpContext httpContext,
            IMediator mediator,
            CancellationToken cancellationToken) =>
        {
            httpContext.Response.Headers.CacheControl = NoStore;
            var response = await mediator.Send(new GetAuthorProfileQueryRequest(), cancellationToken);
            return response.ToHttpResult();
        })
        .WithName("GetAuthorProfile")
        .WithDescription("Aktif, public ve hash doğrulanmış canonical yazar profili (Cache-Control: no-store)")
        .Produces<ApiResponse<AuthorProfileDto>>(200)
        .Produces<ApiResponse<AuthorProfileDto>>(503);

        group.MapGet("/snapshot", async (
            HttpContext httpContext,
            IMediator mediator,
            CancellationToken cancellationToken) =>
        {
            httpContext.Response.Headers.CacheControl = NoStore;
            var response = await mediator.Send(new GetAuthorProfileSnapshotQueryRequest(), cancellationToken);
            return response.ToHttpResult();
        })
        .WithName("GetAuthorProfileSnapshot")
        .WithDescription("Aktif profil sürüm metadatası (profile_id, revision, content_hash); gövde yok")
        .Produces<ApiResponse<AuthorProfileSnapshotDto>>(200)
        .Produces<ApiResponse<AuthorProfileSnapshotDto>>(503);

        return app;
    }
}
