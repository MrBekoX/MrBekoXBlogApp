using BlogApp.Core.Application.Common.Messaging;

namespace BlogApp.Core.Application.Common.AuthorProfile;

/// <summary>Aktif profil sürümünün kimliği (K2: {profile_id, revision, content_hash}); gövde taşımaz.</summary>
public sealed record AuthorProfileSnapshot(string ProfileId, long Revision, string ContentHash)
{
    public AgentProfileSnapshotRef ToRef() => new()
    {
        ProfileId = ProfileId,
        Revision = Revision,
        ContentHash = ContentHash,
    };

    public bool Matches(AgentProfileSnapshotRef? reference) =>
        reference is not null
        && string.Equals(ProfileId, reference.ProfileId, StringComparison.Ordinal)
        && Revision == reference.Revision
        && string.Equals(ContentHash, reference.ContentHash, StringComparison.Ordinal);
}

/// <summary>Bölüm iddiasının kapsamı ve tarih hassasiyeti (kaynak sürümüne ait beyan).</summary>
public sealed record AuthorProfileClaim(
    string? Kind,
    string? AsOf,
    string? Temporal,
    string? Status,
    string? DatePrecision);

public sealed record AuthorProfileLocalizedText(string Tr, string En);

/// <summary>Canonical profil bölümü; <see cref="SectionId"/> = /about anchor'ı (K2).</summary>
public sealed record AuthorProfileSection(
    string SectionId,
    string Anchor,
    string Kind,
    IReadOnlyList<string> HeadingPath,
    AuthorProfileLocalizedText Title,
    string Body,
    IReadOnlyList<string> Notes,
    AuthorProfileClaim Claim,
    bool Retrievable);

/// <summary>Kaynakta yayımlanmış iletişim kanalı (yalnız https).</summary>
public sealed record AuthorProfileContactChannel(string Kind, string Label, string Url);

/// <summary>Doğrulanmış (hash + public + approved) canonical profil içeriği.</summary>
public sealed record AuthorProfileDocument(
    AuthorProfileSnapshot Snapshot,
    string Language,
    string OwnerName,
    IReadOnlyList<string> OwnerAliases,
    string Status,
    bool Approved,
    string? ContentCreatedAt,
    IReadOnlyList<AuthorProfileSection> Sections,
    IReadOnlyList<AuthorProfileContactChannel> ContactChannels);

public enum AuthorProfileAvailability
{
    /// <summary>Manifest + profile.json doğrulandı; public ve onaylı.</summary>
    Available,

    /// <summary>Dizin, manifest veya içerik dosyası bulunamadı.</summary>
    Missing,

    /// <summary>Manifest/profil şeması veya kimlik tutarlılığı bozuk.</summary>
    Invalid,

    /// <summary>sha256(profile.json) manifest content_hash ile uyuşmuyor.</summary>
    HashMismatch,

    /// <summary>status != public veya approved != true (geri çekilmiş/onaysız).</summary>
    NotPublic,
}

/// <summary>Profil kaynağının o anki durumu; yalnız <see cref="AuthorProfileAvailability.Available"/>
/// iken <see cref="Document"/> sunulabilir.</summary>
public sealed record AuthorProfileState(
    AuthorProfileAvailability Availability,
    string? Reason,
    AuthorProfileDocument? Document)
{
    public bool IsAvailable => Availability == AuthorProfileAvailability.Available && Document is not null;

    /// <summary>Aktif ve public profil sürümü; kullanılamıyorsa null.</summary>
    public AuthorProfileSnapshot? ActiveSnapshot => IsAvailable ? Document!.Snapshot : null;

    public static AuthorProfileState Unavailable(AuthorProfileAvailability availability, string reason) =>
        new(availability, reason, null);
}

/// <summary>
/// Tek onaylı, sürümlü public profil kaynağı (K2). Uygulama
/// <c>AuthorProfile:Directory</c> veya <c>AppContext.BaseDirectory/content/author-profile</c>
/// altındaki manifest.json + profile.json'u okur (cwd kullanılmaz), sha256(profile.json ham byte)
/// = manifest.content_hash, status=public, approved=true ve profile_id tutarlılığını doğrular;
/// dosya damgası değişmedikçe sonucu önbellekte tutar. Uyumsuzluk "kullanılamaz" durumudur
/// (sessiz başarı yok).
/// </summary>
public interface IAuthorProfileSource
{
    AuthorProfileState GetCurrent();
}
