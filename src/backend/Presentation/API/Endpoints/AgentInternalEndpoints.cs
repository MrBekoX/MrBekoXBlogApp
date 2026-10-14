using System.Security.Cryptography;
using System.Text;
using BlogApp.Core.Application.Common.Models;
using BlogApp.Core.Application.Common.Options;
using BlogApp.Core.Application.Features.AgentFeature.Queries.GetAgentInternalContentQuery;
using BlogApp.Presentation.Api.Helpers;
using MediatR;
using Microsoft.Extensions.Options;

namespace BlogApp.Presentation.Api.Endpoints;

/// <summary>
/// Agent internal endpoint'leri (Python agent servisi → backend, B12 sabit sözleşme):
///   GET /api/v1/agent/internal/content/{articleId:guid} — yayımlanmış makale anlık görüntüsü
/// KURALLAR: yetki X-Agent-Service-Key header'ıdır; AgentService:InternalApiKey ile
/// SABİT ZAMANLI karşılaştırılır (CryptographicOperations.FixedTimeEquals; uzunluk
/// farkı zamanlamaya sızmaz). Anahtar yapılandırılmamışsa uç HER istek için 404
/// döner (yüzey sızdırma) — endpoint'in varlığı sızmaz. Yalnız Status=Published
/// makaleler sunulur; yoksa/draft ise 404. revision kabul üçlüsünün
/// article_revision kaynağı (BlogPost.ContentRevision), contentHash kabul anındaki
/// AgentRun.ArticleContentHash ile AYNI fonksiyondan (AgentArticleContentHash)
/// üretilir — uyuşmazlık worker stale_snapshot guard'ını tetikler. 200 gövdesi
/// ApiResponse zarfıdır; ``data`` alanı sözleşme alanlarını birebir camelCase
/// taşır (articleId, revision, contentHash, title, content, tags, publishedAt).
/// </summary>
public static class AgentInternalEndpoints
{
    public const string ServiceKeyHeaderName = "X-Agent-Service-Key";

    public static IEndpointRouteBuilder RegisterAgentInternalEndpoints(this IEndpointRouteBuilder app)
    {
        // Internal servis ucu: sürüm müzakeresi yok — sabit v1 yolu (sözleşme).
        var group = app.MapGroup("/api/v1/agent/internal")
            .WithTags("Agent Internal");

        group.MapGet("/content/{articleId:guid}", async (
            Guid articleId,
            HttpContext httpContext,
            IMediator mediator,
            IOptions<AgentServiceSettings> serviceOptions,
            CancellationToken cancellationToken) =>
        {
            var configuredKey = serviceOptions.Value.InternalApiKey;
            if (string.IsNullOrWhiteSpace(configuredKey))
            {
                // Anahtar yapılandırılmamış: internal yüzey kapalı — var olmamış gibi 404.
                return InternalContentNotFound();
            }

            var providedKey = httpContext.Request.Headers[ServiceKeyHeaderName].ToString();
            if (string.IsNullOrEmpty(providedKey))
            {
                return Results.Json(
                    ApiResponse<AgentInternalContentDto>.FailureResult("X-Agent-Service-Key başlığı gerekli."),
                    statusCode: StatusCodes.Status401Unauthorized);
            }

            if (!ServiceKeyMatches(configuredKey, providedKey))
            {
                return Results.Json(
                    ApiResponse<AgentInternalContentDto>.FailureResult("Servis anahtarı geçersiz."),
                    statusCode: StatusCodes.Status401Unauthorized);
            }

            var response = await mediator.Send(new GetAgentInternalContentQueryRequest
            {
                ArticleId = articleId,
            }, cancellationToken);

            return response.IsSuccess
                ? Results.Ok(ApiResponse<AgentInternalContentDto>.SuccessResult(response.Value!))
                : response.ToHttpResult();
        })
        .WithName("GetAgentInternalContent")
        .WithDescription("Yayımlanmış makale anlık görüntüsü (servis anahtarıyla; Python agent retrieval kaynağı)")
        .Produces<ApiResponse<AgentInternalContentDto>>(200)
        .Produces<ApiResponse<AgentInternalContentDto>>(401)
        .Produces<ApiResponse<AgentInternalContentDto>>(404);

        return app;
    }

    /// <summary>Sabit zamanlı anahtar karşılaştırması: her iki girdi de SHA-256'ya
    /// indirgenip FixedTimeEquals ile karşılaştırılır — girdi uzunlukları fark
    /// etmeksizin işlem süresi sabittir.</summary>
    private static bool ServiceKeyMatches(string configuredKey, string providedKey) =>
        CryptographicOperations.FixedTimeEquals(
            SHA256.HashData(Encoding.UTF8.GetBytes(configuredKey)),
            SHA256.HashData(Encoding.UTF8.GetBytes(providedKey)));

    private static IResult InternalContentNotFound() =>
        Results.Json(
            ApiResponse<AgentInternalContentDto>.FailureResult("Kaynak bulunamadı."),
            statusCode: StatusCodes.Status404NotFound);
}
