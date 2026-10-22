using System.Text.Json;
using BlogApp.Core.Application.Common.AuthorProfile;
using BlogApp.Core.Application.Common.Interfaces.Data;
using BlogApp.Core.Application.Common.Options;
using BlogApp.Core.Domain.Enums;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Options;

namespace BlogApp.Core.Application.Features.AgentFeature.Services;

/// <summary>Agent sonucunun sunum denetimi kararı (plan B8 + K6 profil politikası).</summary>
public sealed record AgentResultPresentation
{
    public const string ArticleUnavailableMessage =
        "İçerik kullanılamıyor: sonucun dayandığı makale güncel yayın erişimini kaybetti.";

    /// <summary>Sonuç kullanıcıya sunulabilir: makale kaynaklı tüm kaynakların güncel
    /// yayın erişimi backend'in kendi veritabanında doğrulandı ve (profil sonucuysa) profil
    /// snapshot'ı aktif/public sürümle eşleşti.</summary>
    public required bool IsPresentable { get; init; }

    /// <summary>Güncel yayın erişimi olmayan makale kimlikleri (unpublished/arşiv/silinmiş).</summary>
    public required IReadOnlyList<Guid> UnavailableArticleIds { get; init; }

    /// <summary>Doğrulanan makale kimlikleri (sunulabilir olanlar).</summary>
    public required IReadOnlyList<Guid> AvailableArticleIds { get; init; }

    /// <summary>Profil politikası maskesi (K6); makale maskesinde <see cref="AgentPresentationMask.None"/>.</summary>
    public AgentPresentationMask ProfileMask { get; init; } = AgentPresentationMask.None;

    /// <summary>Sonuç profil politikasına tabi (who_am_i / etkin niyet profile / legacy profile).</summary>
    public bool IsProfileResult { get; init; }

    /// <summary>Kullanıcıya dönen maskeleme gerekçesi: profil maskesinde makine-okur kod
    /// (<c>profile_updated</c> | <c>profile_unavailable</c> | <c>legacy_profile_unavailable</c>),
    /// makale maskesinde mevcut açıklama cümlesi (geriye uyum).</summary>
    public string? UnavailableReason =>
        IsPresentable
            ? null
            : AgentProfilePresentationPolicy.CodeOf(ProfileMask) ?? ArticleUnavailableMessage;

    /// <summary>Maskelemenin insan-okur açıklaması + yeni sorgu önerisi.</summary>
    public string? UnavailableMessage =>
        IsPresentable
            ? null
            : AgentProfilePresentationPolicy.MessageOf(ProfileMask) ?? ArticleUnavailableMessage;
}

/// <summary>
/// B8 sunum katmanı denetimi (plan B8): "backend, makale kaynaklı sonucu kullanıcıya
/// sunmadan önce kaynakların güncel yayın erişimini kendi veritabanından kontrol etsin.
/// Yayından kaldırılmış içeriğe dayanan sonucu ve eski cache'i sunmasın; uygun içerik
/// kullanılamıyor durumu üretsin." K6 ile profil sonuçları için aktif profil snapshot
/// denetimi eklenir (<see cref="AgentProfilePresentationPolicy"/>).
///
/// Denetim doğrudan backend DB'sine (IApplicationDbContext) ve canonical profil kaynağına gider —
/// sonuç cache'i KULLANMAZ. Denetim yalnız okur; sonuç kaydını değiştirmez (maskelenme sunum
/// yüzeylerinin kararıdır: GET status, SignalR terminal bildirimi, replay, konuşma geçmişi).
/// </summary>
public interface IAgentResultPresentationGuard
{
    Task<AgentResultPresentation> CheckAsync(Guid runId, CancellationToken cancellationToken = default);

    /// <summary>Run kaydı zaten elde varsa tekrar okumadan denetler.</summary>
    Task<AgentResultPresentation> CheckAsync(AgentRunResultContext result, CancellationToken cancellationToken = default);
}

/// <summary>Terminal sonucun denetim için gereken minimum bilgisi (B5 projection kolonları +
/// kabulde yazılan kalıcı bağlam: wire sürümü, konu, pinlenmiş profil snapshot'ı).</summary>
public sealed record AgentRunResultContext(
    Guid RunId,
    Guid? ArticleId,
    string? ResultJson,
    string? ContextSnapshotJson = null);

/// <summary>Profil kaynağı ve wire anahtarı opsiyoneldir: verilmezse profil "kullanılamaz" ve
/// v2 anahtarı kapalı sayılır (fail-closed; v1 makale davranışı birebir korunur).</summary>
public sealed class AgentResultPresentationGuard(
    IApplicationDbContext dbContext,
    IAuthorProfileSource? profileSource = null,
    IOptions<AgentWireV2Settings>? wireOptions = null) : IAgentResultPresentationGuard
{
    public async Task<AgentResultPresentation> CheckAsync(Guid runId, CancellationToken cancellationToken = default)
    {
        var run = await dbContext.AgentRuns
            .AsNoTracking()
            .Where(r => r.Id == runId)
            .Select(r => new AgentRunResultContext(r.Id, r.ArticleId, r.ResultJson, r.ContextSnapshotJson))
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
        var decision = AgentProfilePresentationPolicy.Evaluate(
            AgentRunWireContext.Parse(result.ContextSnapshotJson),
            AgentResultFacts.Parse(result.ResultJson),
            profileSource?.GetCurrent().ActiveSnapshot,
            wireOptions?.Value.Enabled ?? false);

        if (decision.Mask != AgentPresentationMask.None)
        {
            return new AgentResultPresentation
            {
                IsPresentable = false,
                UnavailableArticleIds = [],
                AvailableArticleIds = [],
                ProfileMask = decision.Mask,
                IsProfileResult = true,
            };
        }

        var referenced = CollectArticleReferences(result, includeContextArticle: !decision.ExcludeContextArticle);

        if (referenced.Count == 0)
        {
            return new AgentResultPresentation
            {
                IsPresentable = true,
                UnavailableArticleIds = [],
                AvailableArticleIds = [],
                IsProfileResult = decision.ProfileGoverned,
            };
        }

        // IgnoreQueryFilters: soft-delete filter'ı atlanır — silinmiş makale "erişim yok"
        // kararı üretir; filtreli sorgu onu bulamaz ve silinmiş içeriğe dayanan sonuç
        // yanlışlıkla sunulabilirdi.
        var referencedIds = referenced.Distinct().ToList();
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
            IsProfileResult = decision.ProfileGoverned,
        };
    }

    /// <summary>Sonucun makale kaynaklı referanslarını toplar: B5 terminal snapshot'ındaki
    /// citations (kind=article) + run bağlam makalesi (bağlam da "makale kaynaklı"dır; yalnız
    /// doğrulanmış profil sonucunda dışarıda kalır). Bozuk/eksik snapshot'ta bağlam makalesi yine
    /// denetlenir; snapshot JSON'u asla sunuma dahil edilmez.</summary>
    private static List<Guid> CollectArticleReferences(AgentRunResultContext result, bool includeContextArticle)
    {
        var ids = new List<Guid>();
        if (includeContextArticle && result.ArticleId is { } contextArticle)
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
