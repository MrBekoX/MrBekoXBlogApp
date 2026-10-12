using System.Text.Json;
using BlogApp.Core.Application.Common.Interfaces.Data;
using BlogApp.Core.Domain.Enums;
using Microsoft.EntityFrameworkCore;

namespace BlogApp.Core.Application.Features.AgentFeature.Services;

/// <summary>Makale kaynaklı agent sonucunun sunum denetimi kararı (plan B8).</summary>
public sealed record AgentResultPresentation
{
    /// <summary>Sonuç kullanıcıya sunulabilir: makale kaynaklı tüm kaynakların güncel
    /// yayın erişimi backend'in kendi veritabanında doğrulandı.</summary>
    public required bool IsPresentable { get; init; }

    /// <summary>Güncel yayın erişimi olmayan makale kimlikleri (unpublished/arşiv/silinmiş).</summary>
    public required IReadOnlyList<Guid> UnavailableArticleIds { get; init; }

    /// <summary>Doğrulanan makale kimlikleri (sunulabilir olanlar).</summary>
    public required IReadOnlyList<Guid> AvailableArticleIds { get; init; }

    /// <summary>İçerik kullanılamıyor durumunun kullanıcıya gösterilecek kısa gerekçesi.</summary>
    public string? UnavailableReason =>
        IsPresentable ? null : "İçerik kullanılamıyor: sonucun dayandığı makale güncel yayın erişimini kaybetti.";
}

/// <summary>
/// B8 sunum katmanı denetimi (plan B8): "backend, makale kaynaklı sonucu kullanıcıya
/// sunmadan önce kaynakların güncel yayın erişimini kendi veritabanından kontrol etsin.
/// Yayından kaldırılmış içeriğe dayanan sonucu ve eski cache'i sunmasın; uygun içerik
/// kullanılamıyor durumu üretsin."
///
/// Denetim doğrudan backend DB'sine (IApplicationDbContext) gider — cache KULLANMAZ;
/// asenkron içerik olayları nedeniyle agent indeksi kısa süre geride kalsa bile
/// sunum kararı backend'in anlık yayın durumuyla verilir. Denetim yalnız okur;
/// sonuç kaydını değiştirmez (maskelenme B10 sunum endpoint'inin kararıdır).
/// </summary>
public interface IAgentResultPresentationGuard
{
    Task<AgentResultPresentation> CheckAsync(Guid runId, CancellationToken cancellationToken = default);

    /// <summary>Run kaydı zaten elde varsa tekrar okumadan denetler.</summary>
    Task<AgentResultPresentation> CheckAsync(AgentRunResultContext result, CancellationToken cancellationToken = default);
}

/// <summary>Terminal sonucun denetim için gereken minimum bilgisi (B5 projection kolonlarından).</summary>
public sealed record AgentRunResultContext(Guid RunId, Guid? ArticleId, string? ResultJson);

public sealed class AgentResultPresentationGuard(IApplicationDbContext dbContext) : IAgentResultPresentationGuard
{
    private static readonly JsonSerializerOptions SerializerOptions = new()
    {
        PropertyNameCaseInsensitive = true,
    };

    public async Task<AgentResultPresentation> CheckAsync(Guid runId, CancellationToken cancellationToken = default)
    {
        var run = await dbContext.AgentRuns
            .AsNoTracking()
            .Where(r => r.Id == runId)
            .Select(r => new AgentRunResultContext(r.Id, r.ArticleId, r.ResultJson))
            .FirstOrDefaultAsync(cancellationToken);

        if (run is null)
        {
            return new AgentResultPresentation
            {
                IsPresentable = false,
                UnavailableArticleIds = [],
                AvailableArticleIds = [],
            };
        }

        return await CheckAsync(run, cancellationToken);
    }

    public async Task<AgentResultPresentation> CheckAsync(AgentRunResultContext result, CancellationToken cancellationToken = default)
    {
        var referenced = CollectArticleReferences(result);

        if (referenced.Count == 0)
        {
            return new AgentResultPresentation
            {
                IsPresentable = true,
                UnavailableArticleIds = [],
                AvailableArticleIds = [],
            };
        }

        // IgnoreQueryFilters: soft-delete filter'ı atlanır — silinmiş makale "erişim yok"
        // kararı üretir; filtreli sorgu onu bulamaz ve silinmiş içeriğe dayanan sonuç
        // yanlışlıkla sunulabilirdi.
        var referencedIds = referenced.Select(id => id).Distinct().ToList();
        var states = await dbContext.Posts
            .IgnoreQueryFilters()
            .AsNoTracking()
            .Where(p => referencedIds.Contains(p.Id))
            .Select(p => new { p.Id, p.IsDeleted, p.Status })
            .ToDictionaryAsync(p => p.Id, p => (p.IsDeleted, p.Status), cancellationToken);

        var available = new List<Guid>();
        var unavailable = new List<Guid>();
        foreach (var id in referencedIds)
        {
            if (states.TryGetValue(id, out var state)
                && !state.IsDeleted
                && state.Status == PostStatus.Published)
            {
                available.Add(id);
            }
            else
            {
                unavailable.Add(id);
            }
        }

        return new AgentResultPresentation
        {
            IsPresentable = unavailable.Count == 0,
            UnavailableArticleIds = unavailable,
            AvailableArticleIds = available,
        };
    }

    /// <summary>Sonucun makale kaynaklı referanslarını toplar: B5 terminal snapshot'ındaki
    /// citations (kind=article) + run bağlam makalesi (bağlam da "makale kaynaklı"dır).
    /// Bozuk/eksik snapshot'ta bağlam makalesi yine denetlenir; snapshot JSON'u asla
    /// sunuma dahil edilmez.</summary>
    private static List<Guid> CollectArticleReferences(AgentRunResultContext result)
    {
        var ids = new List<Guid>();
        if (result.ArticleId is { } contextArticle)
        {
            ids.Add(contextArticle);
        }

        if (string.IsNullOrWhiteSpace(result.ResultJson))
        {
            return ids;
        }

        try
        {
            using var document = JsonDocument.Parse(result.ResultJson);
            if (document.RootElement.ValueKind == JsonValueKind.Object
                && document.RootElement.TryGetProperty("citations", out var citations)
                && citations.ValueKind == JsonValueKind.Array)
            {
                foreach (var citation in citations.EnumerateArray())
                {
                    if (citation.ValueKind != JsonValueKind.Object
                        || !citation.TryGetProperty("kind", out var kind)
                        || kind.GetString() != "article"
                        || !citation.TryGetProperty("article_id", out var articleId)
                        || !Guid.TryParse(articleId.GetString(), out var parsed))
                    {
                        continue;
                    }

                    ids.Add(parsed);
                }
            }
        }
        catch (JsonException)
        {
            // Bozuk snapshot: bağlam makalesi denetimiyle sınırlı kalır; sonuç snapshot'ı
            // kendisi B10 sunumunda ayrıca doğrulanır.
        }

        return ids;
    }
}
