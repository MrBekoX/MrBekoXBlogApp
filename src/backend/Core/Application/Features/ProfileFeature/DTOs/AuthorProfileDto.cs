using BlogApp.Core.Application.Common.AuthorProfile;

namespace BlogApp.Core.Application.Features.ProfileFeature.DTOs;

/// <summary>GET /api/v1/profile yanıtı: aktif, public ve hash doğrulanmış canonical profil (K2/K6).
/// /about sayfası ve istemci tek kaynak olarak bunu okur (ayrı biyografi kopyası tutulmaz).</summary>
public sealed record AuthorProfileDto(
    string ProfileId,
    long Revision,
    string ContentHash,
    string Language,
    string OwnerName,
    string Status,
    string? ContentCreatedAt,
    IReadOnlyList<AuthorProfileSectionDto> Sections,
    IReadOnlyList<AuthorProfileContactChannelDto> ContactChannels)
{
    public static AuthorProfileDto From(AuthorProfileDocument document) => new(
        document.Snapshot.ProfileId,
        document.Snapshot.Revision,
        document.Snapshot.ContentHash,
        document.Language,
        document.OwnerName,
        document.Status,
        document.ContentCreatedAt,
        document.Sections.Select(AuthorProfileSectionDto.From).ToList(),
        document.ContactChannels.Select(c => new AuthorProfileContactChannelDto(c.Kind, c.Label, c.Url)).ToList());
}

/// <summary>Profil bölümü; <see cref="Anchor"/> = <see cref="SectionId"/> = /about#anchor.</summary>
public sealed record AuthorProfileSectionDto(
    string SectionId,
    string Anchor,
    string Kind,
    IReadOnlyList<string> HeadingPath,
    AuthorProfileTitleDto Title,
    string Body,
    IReadOnlyList<string> Notes,
    AuthorProfileClaimDto Claim)
{
    public static AuthorProfileSectionDto From(AuthorProfileSection section) => new(
        section.SectionId,
        section.Anchor,
        section.Kind,
        section.HeadingPath,
        new AuthorProfileTitleDto(section.Title.Tr, section.Title.En),
        section.Body,
        section.Notes,
        new AuthorProfileClaimDto(
            section.Claim.Kind,
            section.Claim.AsOf,
            section.Claim.Temporal,
            section.Claim.Status,
            section.Claim.DatePrecision));
}

public sealed record AuthorProfileTitleDto(string Tr, string En);

/// <summary>Bölüm iddiasının kaynak tarihli kapsamı (as_of, temporal, status, tarih hassasiyeti).</summary>
public sealed record AuthorProfileClaimDto(
    string? Kind,
    string? AsOf,
    string? Temporal,
    string? Status,
    string? DatePrecision);

public sealed record AuthorProfileContactChannelDto(string Kind, string Label, string Url);

/// <summary>GET /api/v1/profile/snapshot: yalnız aktif sürüm metadatası (drift kontrolü için; gövde yok).</summary>
public sealed record AuthorProfileSnapshotDto(
    string ProfileId,
    long Revision,
    string ContentHash,
    string Status);
