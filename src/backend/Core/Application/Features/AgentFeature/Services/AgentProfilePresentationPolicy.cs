using System.Text.Json;
using BlogApp.Core.Application.Common.AuthorProfile;
using BlogApp.Core.Application.Common.Messaging;

namespace BlogApp.Core.Application.Features.AgentFeature.Services;

/// <summary>Terminal sonuç snapshot'ının (ResultJson) sunum kararına giren olguları.</summary>
public sealed record AgentResultCitationFacts(
    string? Kind,
    string? ArticleId,
    string? ProfileId,
    long? ProfileRevision,
    string? ProfileContentHash,
    string? SectionId,
    long? ChunkIndex,
    string? Url,
    string? SourceId);

public sealed record AgentResultFacts(
    bool Corrupt,
    bool HasContent,
    string? RunIntent,
    string? SourceScope,
    AgentProfileSnapshotRef? ProfileSnapshot,
    IReadOnlyList<AgentResultCitationFacts> Citations)
{
    public static readonly AgentResultFacts Empty = new(false, false, null, null, null, []);

    /// <summary>ResultJson'u ayrıştırır; bozuk JSON <see cref="Corrupt"/> işaretlenir (ham JSON
    /// asla sunulmaz).</summary>
    public static AgentResultFacts Parse(string? resultJson)
    {
        if (string.IsNullOrWhiteSpace(resultJson))
        {
            return Empty;
        }

        try
        {
            using var document = JsonDocument.Parse(resultJson);
            var root = document.RootElement;
            if (root.ValueKind != JsonValueKind.Object)
            {
                return Empty with { Corrupt = true };
            }

            var hasContent = IsText(root, "answer") || IsText(root, "report");

            AgentProfileSnapshotRef? snapshot = null;
            if (root.TryGetProperty("profile_snapshot", out var snapshotElement)
                && snapshotElement.ValueKind == JsonValueKind.Object
                && Text(snapshotElement, "profile_id") is { } profileId
                && Long(snapshotElement, "revision") is { } revision
                && Text(snapshotElement, "content_hash") is { } contentHash)
            {
                snapshot = new AgentProfileSnapshotRef { ProfileId = profileId, Revision = revision, ContentHash = contentHash };
            }

            var citations = new List<AgentResultCitationFacts>();
            if (root.TryGetProperty("citations", out var citationsElement) && citationsElement.ValueKind == JsonValueKind.Array)
            {
                foreach (var citation in citationsElement.EnumerateArray())
                {
                    if (citation.ValueKind != JsonValueKind.Object)
                    {
                        continue;
                    }

                    citations.Add(new AgentResultCitationFacts(
                        Text(citation, "kind"),
                        Text(citation, "article_id"),
                        Text(citation, "profile_id"),
                        Long(citation, "profile_revision"),
                        Text(citation, "profile_content_hash"),
                        Text(citation, "section_id"),
                        Long(citation, "chunk_index"),
                        Text(citation, "url"),
                        Text(citation, "source_id")));
                }
            }

            return new AgentResultFacts(
                Corrupt: false,
                hasContent,
                Text(root, "run_intent"),
                Text(root, "source_scope"),
                snapshot,
                citations);
        }
        catch (JsonException)
        {
            return Empty with { Corrupt = true };
        }
    }

    private static bool IsText(JsonElement element, string name) =>
        element.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.String
        && !string.IsNullOrEmpty(value.GetString());

    private static string? Text(JsonElement element, string name) =>
        element.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.String ? value.GetString() : null;

    private static long? Long(JsonElement element, string name) =>
        element.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.Number && value.TryGetInt64(out var number)
            ? number
            : null;
}

/// <summary>Profil sunum maskesi (K6). Kodlar istemciye <c>unavailableReason</c> olarak döner.</summary>
public enum AgentPresentationMask
{
    None,
    ProfileUpdated,
    ProfileUnavailable,
    LegacyProfileUnavailable,
}

public sealed record AgentProfilePresentationDecision(
    bool ProfileGoverned,
    AgentPresentationMask Mask,
    bool ExcludeContextArticle)
{
    public static readonly AgentProfilePresentationDecision NotGoverned = new(false, AgentPresentationMask.None, false);
}

/// <summary>
/// Profil sonuçlarının TEK sunum politikası (K6; GET status, SignalR terminal bildirimi, replay ve
/// konuşma geçmişi aynı kararı kullanır). Saf fonksiyondur; DB'ye gitmez — makale yayın denetimi
/// <see cref="AgentResultPresentationGuard"/>'dadır.
/// <list type="bullet">
/// <item>v1 run + source_scope=profile: AgentWireV2 açıksa <c>legacy_profile_unavailable</c>
///   (legacy A9 sonucu yeni kaynağa bağlanamaz; provenance gevşetilmez); kapalıysa eski davranış.</item>
/// <item>v2 run'da konu who_am_i, run_intent=profile, source_scope=profile veya profile kaynağı
///   taşıyan sonuç profil sonucudur: profil public/aktif olmalı, run_intent=profile olmalı,
///   payload profile_snapshot kabulde pinlenen snapshot'a eşit olmalı, kaynaklar yalnız profile ve
///   snapshot ile tutarlı olmalı (aksi halde <c>profile_unavailable</c>); snapshot aktif sürümden
///   farklıysa <c>profile_updated</c>.</item>
/// <item>Doğrulanmış profil sonucu (yukarıdakilerin hepsi) makale kaynağı taşımadığından
///   run.ArticleId sunum bağımlılığı değildir (AUTO→PROFILE); yalnız source_scope iddiası bu
///   gevşetmeyi sağlamaz.</item>
/// </list>
/// İçerik taşımayan sonuçlar (failed/cancelled) profil kuralına girmez (sunulacak gövde yoktur).
/// </summary>
public static class AgentProfilePresentationPolicy
{
    public const string ProfileUpdatedCode = "profile_updated";
    public const string ProfileUnavailableCode = "profile_unavailable";
    public const string LegacyProfileUnavailableCode = "legacy_profile_unavailable";

    public static string? CodeOf(AgentPresentationMask mask) => mask switch
    {
        AgentPresentationMask.ProfileUpdated => ProfileUpdatedCode,
        AgentPresentationMask.ProfileUnavailable => ProfileUnavailableCode,
        AgentPresentationMask.LegacyProfileUnavailable => LegacyProfileUnavailableCode,
        _ => null,
    };

    /// <summary>Kullanıcıya gösterilecek açıklama + yeni sorgu önerisi.</summary>
    public static string? MessageOf(AgentPresentationMask mask) => mask switch
    {
        AgentPresentationMask.ProfileUpdated =>
            "Profil bilgisi güncellendi; bu yanıt eski bir profil sürümüne dayanıyor. Güncel bilgi için soruyu yeniden sorun.",
        AgentPresentationMask.ProfileUnavailable =>
            "Profil bilgisi şu an kullanılamıyor; bu yanıt doğrulanamadığı için gösterilmiyor. Daha sonra soruyu yeniden sorabilirsiniz.",
        AgentPresentationMask.LegacyProfileUnavailable =>
            "Bu yanıt eski profil akışıyla üretildi ve güncel profil kaynağıyla doğrulanamıyor. Güncel bilgi için soruyu yeniden sorun.",
        _ => null,
    };

    public static AgentProfilePresentationDecision Evaluate(
        AgentRunWireContext context,
        AgentResultFacts facts,
        AuthorProfileSnapshot? activeSnapshot,
        bool wireV2Enabled)
    {
        if (!context.IsV2)
        {
            return facts.HasContent && wireV2Enabled && facts.SourceScope == "profile"
                ? new AgentProfilePresentationDecision(true, AgentPresentationMask.LegacyProfileUnavailable, false)
                : AgentProfilePresentationDecision.NotGoverned;
        }

        var claimsProfile = context.IsWhoAmI
                            || facts.RunIntent == "profile"
                            || facts.SourceScope == "profile"
                            || facts.Citations.Any(c => c.Kind == "profile");
        if (!claimsProfile)
        {
            return AgentProfilePresentationDecision.NotGoverned;
        }

        if (!facts.HasContent && !facts.Corrupt)
        {
            // Gövdesiz (failed/cancelled) sonuç: sunulacak profil içeriği yoktur; who_am_i'de bağlam
            // makalesi zaten yoktur.
            return new AgentProfilePresentationDecision(true, AgentPresentationMask.None, context.IsWhoAmI);
        }

        if (facts.Corrupt
            || activeSnapshot is null
            || facts.RunIntent != "profile"
            || facts.ProfileSnapshot is null
            || context.PinnedProfile is null
            || !facts.ProfileSnapshot.SameAs(context.PinnedProfile)
            || facts.Citations.Any(c => !IsConsistentProfileCitation(c, facts.ProfileSnapshot)))
        {
            return new AgentProfilePresentationDecision(true, AgentPresentationMask.ProfileUnavailable, false);
        }

        if (!activeSnapshot.Matches(facts.ProfileSnapshot))
        {
            return new AgentProfilePresentationDecision(true, AgentPresentationMask.ProfileUpdated, false);
        }

        // Doğrulanmış etkin niyet = profile ve makale kaynağı yok: bağlam makalesi sunum bağımlılığı değil.
        return new AgentProfilePresentationDecision(true, AgentPresentationMask.None, ExcludeContextArticle: true);
    }

    /// <summary>Profile kaynağı tutarlılığı: tür profile, snapshot üçlüsü eşit, bölüm kimliği ve
    /// canonical URL/kaynak kimliği biçimi (URL modelden alınmaz; yeniden doğrulanır).</summary>
    public static bool IsConsistentProfileCitation(AgentResultCitationFacts citation, AgentProfileSnapshotRef snapshot) =>
        citation.Kind == "profile"
        && citation.ArticleId is null
        && citation.ProfileId == snapshot.ProfileId
        && citation.ProfileRevision == snapshot.Revision
        && citation.ProfileContentHash == snapshot.ContentHash
        && citation.SectionId is { } sectionId
        && AgentContractFormats.IsValidSectionId(sectionId)
        && citation.Url == AgentContractFormats.ComposeProfileUrl(sectionId)
        && citation.ChunkIndex is { } chunk
        && citation.SourceId == AgentContractFormats.ComposeProfileSourceId(
            snapshot.ProfileId, snapshot.Revision, snapshot.ContentHash, sectionId, chunk);
}
