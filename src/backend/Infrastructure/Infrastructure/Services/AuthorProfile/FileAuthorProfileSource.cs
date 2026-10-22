using System.Globalization;
using System.Security.Cryptography;
using System.Text.Json;
using BlogApp.Core.Application.Common.AuthorProfile;
using BlogApp.Core.Application.Common.Messaging;
using BlogApp.Core.Application.Common.Options;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Logging.Abstractions;
using Microsoft.Extensions.Options;

namespace BlogApp.Infrastructure.Services.AuthorProfile;

/// <summary>
/// Canonical yazar profilinin dosya tabanlı okuyucusu (K2). Her okuma dosya damgasını
/// (manifest.json + profile.json: uzunluk + son yazma zamanı) karşılaştırır; değişmediyse
/// doğrulanmış sonuç önbellekten döner, değiştiyse yeniden okunup doğrulanır (yeni sürüm
/// doğrulanınca atomik olarak aktifleşir). Doğrulama: manifest şeması, profile_id biçimi,
/// revision ≥ 1, content_file = profile.json, sha256(profile.json ham byte) = content_hash,
/// status = public, approved = true, profile.json şeması/profile_id/bölüm kimlikleri
/// (section_id = anchor, benzersiz) ve https iletişim kanalları. Herhangi bir uyumsuzluk
/// "kullanılamaz" durumudur; içerik sunulmaz.
/// </summary>
public sealed class FileAuthorProfileSource : IAuthorProfileSource
{
    public const string ManifestFileName = "manifest.json";
    public const string ContentFileName = "profile.json";
    public const string ProfileSchema = "author-profile/1";

    private readonly ILogger _logger;
    private readonly object _gate = new();
    private string? _cachedStamp;
    private AuthorProfileState? _cachedState;

    public FileAuthorProfileSource(IOptions<AuthorProfileSettings> options, ILogger<FileAuthorProfileSource> logger)
        : this(ResolveDirectory(options.Value.Directory), logger)
    {
    }

    public FileAuthorProfileSource(string directory, ILogger? logger = null)
    {
        ProfileDirectory = directory;
        _logger = logger ?? NullLogger.Instance;
    }

    /// <summary>Çözümlenmiş profil dizini (tanılama).</summary>
    public string ProfileDirectory { get; }

    /// <summary>Konum çözümü: yapılandırma → mutlak yol; göreli → AppContext.BaseDirectory'ye göre;
    /// boş → AppContext.BaseDirectory/content/author-profile. cwd hiçbir dalda kullanılmaz.</summary>
    public static string ResolveDirectory(string? configured)
    {
        if (string.IsNullOrWhiteSpace(configured))
        {
            return Path.Combine(AppContext.BaseDirectory, "content", "author-profile");
        }

        return Path.IsPathRooted(configured)
            ? configured
            : Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, configured));
    }

    public AuthorProfileState GetCurrent()
    {
        var stamp = ComputeStamp();
        lock (_gate)
        {
            if (_cachedState is not null && string.Equals(stamp, _cachedStamp, StringComparison.Ordinal))
            {
                return _cachedState;
            }

            var state = Load();
            LogTransition(_cachedState, state);
            _cachedStamp = stamp;
            _cachedState = state;
            return state;
        }
    }

    private string ComputeStamp()
    {
        return string.Join('|', FileStamp(ManifestFileName), FileStamp(ContentFileName));

        string FileStamp(string name)
        {
            var info = new FileInfo(Path.Combine(ProfileDirectory, name));
            return info.Exists
                ? string.Create(CultureInfo.InvariantCulture, $"{info.Length}:{info.LastWriteTimeUtc.Ticks}")
                : "missing";
        }
    }

    private void LogTransition(AuthorProfileState? previous, AuthorProfileState current)
    {
        if (current.IsAvailable)
        {
            var snapshot = current.Document!.Snapshot;
            _logger.LogInformation(
                "[AuthorProfile] aktif profil: {ProfileId} rev {Revision} hash {Hash}",
                snapshot.ProfileId, snapshot.Revision, snapshot.ContentHash[..12]);
            return;
        }

        if (previous is null || previous.Availability != current.Availability || previous.Reason != current.Reason)
        {
            _logger.LogWarning(
                "[AuthorProfile] profil kaynağı kullanılamıyor ({Availability}): {Reason} (dizin {Directory})",
                current.Availability, current.Reason, ProfileDirectory);
        }
    }

    private AuthorProfileState Load()
    {
        try
        {
            return LoadCore();
        }
        catch (IOException exception)
        {
            return AuthorProfileState.Unavailable(AuthorProfileAvailability.Missing, $"dosya okunamadı: {exception.Message}");
        }
        catch (UnauthorizedAccessException exception)
        {
            return AuthorProfileState.Unavailable(AuthorProfileAvailability.Missing, $"dosya erişimi reddedildi: {exception.Message}");
        }
    }

    private AuthorProfileState LoadCore()
    {
        if (!Directory.Exists(ProfileDirectory))
        {
            return AuthorProfileState.Unavailable(AuthorProfileAvailability.Missing, "profil dizini bulunamadı");
        }

        var manifestPath = Path.Combine(ProfileDirectory, ManifestFileName);
        if (!File.Exists(manifestPath))
        {
            return AuthorProfileState.Unavailable(AuthorProfileAvailability.Missing, "manifest.json bulunamadı");
        }

        Manifest manifest;
        try
        {
            using var manifestDocument = JsonDocument.Parse(StripBom(File.ReadAllBytes(manifestPath)));
            if (!TryReadManifest(manifestDocument.RootElement, out manifest, out var manifestError))
            {
                return AuthorProfileState.Unavailable(AuthorProfileAvailability.Invalid, manifestError);
            }
        }
        catch (JsonException)
        {
            return AuthorProfileState.Unavailable(AuthorProfileAvailability.Invalid, "manifest.json geçerli JSON değil");
        }

        var contentPath = Path.Combine(ProfileDirectory, ContentFileName);
        if (!File.Exists(contentPath))
        {
            return AuthorProfileState.Unavailable(AuthorProfileAvailability.Missing, "profile.json bulunamadı");
        }

        var contentBytes = File.ReadAllBytes(contentPath);
        var actualHash = Convert.ToHexString(SHA256.HashData(contentBytes)).ToLowerInvariant();
        if (!string.Equals(actualHash, manifest.ContentHash, StringComparison.Ordinal))
        {
            return AuthorProfileState.Unavailable(AuthorProfileAvailability.HashMismatch,
                "sha256(profile.json) manifest content_hash ile uyuşmuyor");
        }

        if (!string.Equals(manifest.Status, "public", StringComparison.Ordinal) || !manifest.Approved)
        {
            return AuthorProfileState.Unavailable(AuthorProfileAvailability.NotPublic,
                $"profil yayımda değil (status={manifest.Status}, approved={manifest.Approved})");
        }

        try
        {
            using var profileDocument = JsonDocument.Parse(StripBom(contentBytes));
            return TryReadProfile(profileDocument.RootElement, manifest, out var document, out var profileError)
                ? new AuthorProfileState(AuthorProfileAvailability.Available, null, document)
                : AuthorProfileState.Unavailable(AuthorProfileAvailability.Invalid, profileError);
        }
        catch (JsonException)
        {
            return AuthorProfileState.Unavailable(AuthorProfileAvailability.Invalid, "profile.json geçerli JSON değil");
        }
    }

    private sealed record Manifest(
        string ProfileId,
        long Revision,
        string Language,
        string ContentHash,
        string Status,
        bool Approved,
        string? ContentCreatedAt);

    private static bool TryReadManifest(JsonElement root, out Manifest manifest, out string error)
    {
        manifest = null!;
        error = string.Empty;
        if (root.ValueKind != JsonValueKind.Object)
        {
            error = "manifest bir JSON nesnesi olmalıdır";
            return false;
        }

        if (!root.TryGetProperty("manifest_schema", out var schema) || schema.ValueKind != JsonValueKind.Number
            || !schema.TryGetInt32(out var schemaVersion) || schemaVersion != 1)
        {
            error = "desteklenmeyen manifest_schema";
            return false;
        }

        var profileId = ReadString(root, "profile_id");
        if (profileId is null || !AgentContractFormats.IsValidProfileId(profileId))
        {
            error = "manifest profile_id geçersiz";
            return false;
        }

        if (!root.TryGetProperty("revision", out var revisionElement) || revisionElement.ValueKind != JsonValueKind.Number
            || !revisionElement.TryGetInt64(out var revision) || revision < 1)
        {
            error = "manifest revision ≥ 1 tamsayı olmalıdır";
            return false;
        }

        if (!string.Equals(ReadString(root, "content_file"), ContentFileName, StringComparison.Ordinal))
        {
            error = "manifest content_file yalnız profile.json olabilir";
            return false;
        }

        var hash = ReadString(root, "content_hash");
        if (hash is null || !AgentContractFormats.IsValidHashHex(hash))
        {
            error = "manifest content_hash 64 haneli küçük harf SHA-256 hex olmalıdır";
            return false;
        }

        var status = ReadString(root, "status");
        if (status is null)
        {
            error = "manifest status eksik";
            return false;
        }

        if (!root.TryGetProperty("approved", out var approvedElement)
            || approvedElement.ValueKind is not (JsonValueKind.True or JsonValueKind.False))
        {
            error = "manifest approved boolean olmalıdır";
            return false;
        }

        var language = ReadString(root, "language");
        if (language is null || !AgentContractFormats.IsValidLanguageCode(language))
        {
            error = "manifest language geçersiz";
            return false;
        }

        manifest = new Manifest(profileId, revision, language, hash, status, approvedElement.GetBoolean(),
            ReadString(root, "content_created_at"));
        return true;
    }

    private static bool TryReadProfile(JsonElement root, Manifest manifest, out AuthorProfileDocument document, out string error)
    {
        document = null!;
        error = string.Empty;
        if (root.ValueKind != JsonValueKind.Object || ReadString(root, "schema") != ProfileSchema)
        {
            error = $"profile.json şeması {ProfileSchema} değil";
            return false;
        }

        if (!string.Equals(ReadString(root, "profile_id"), manifest.ProfileId, StringComparison.Ordinal))
        {
            error = "profile.json profile_id manifest ile uyuşmuyor";
            return false;
        }

        if (!root.TryGetProperty("owner", out var owner) || owner.ValueKind != JsonValueKind.Object
            || ReadString(owner, "name") is not { Length: > 0 } ownerName)
        {
            error = "profile.json owner.name eksik";
            return false;
        }

        if (!root.TryGetProperty("sections", out var sectionsElement) || sectionsElement.ValueKind != JsonValueKind.Array)
        {
            error = "profile.json sections dizisi eksik";
            return false;
        }

        var sections = new List<AuthorProfileSection>();
        var seen = new HashSet<string>(StringComparer.Ordinal);
        foreach (var section in sectionsElement.EnumerateArray())
        {
            if (!TryReadSection(section, out var parsed, out error))
            {
                return false;
            }

            if (!seen.Add(parsed.SectionId))
            {
                error = $"yinelenen section_id: {parsed.SectionId}";
                return false;
            }

            sections.Add(parsed);
        }

        if (sections.Count == 0)
        {
            error = "profile.json bölüm içermiyor";
            return false;
        }

        var channels = new List<AuthorProfileContactChannel>();
        if (root.TryGetProperty("privacy", out var privacy) && privacy.ValueKind == JsonValueKind.Object
            && privacy.TryGetProperty("contact_channels", out var channelsElement))
        {
            if (channelsElement.ValueKind != JsonValueKind.Array)
            {
                error = "privacy.contact_channels dizi olmalıdır";
                return false;
            }

            foreach (var channel in channelsElement.EnumerateArray())
            {
                var kind = ReadString(channel, "kind");
                var label = ReadString(channel, "label");
                var url = ReadString(channel, "url");
                if (kind is null || label is null || url is null
                    || !Uri.TryCreate(url, UriKind.Absolute, out var parsedUrl) || parsedUrl.Scheme != Uri.UriSchemeHttps)
                {
                    error = "iletişim kanalı kind/label/https url taşımalıdır";
                    return false;
                }

                channels.Add(new AuthorProfileContactChannel(kind, label, url));
            }
        }

        document = new AuthorProfileDocument(
            new AuthorProfileSnapshot(manifest.ProfileId, manifest.Revision, manifest.ContentHash),
            manifest.Language,
            ownerName,
            StringList(owner, "aliases"),
            manifest.Status,
            manifest.Approved,
            manifest.ContentCreatedAt,
            sections,
            channels);
        return true;
    }

    private static bool TryReadSection(JsonElement section, out AuthorProfileSection parsed, out string error)
    {
        parsed = null!;
        error = string.Empty;
        if (section.ValueKind != JsonValueKind.Object)
        {
            error = "bölüm bir JSON nesnesi olmalıdır";
            return false;
        }

        var sectionId = ReadString(section, "section_id");
        if (sectionId is null || !AgentContractFormats.IsValidSectionId(sectionId))
        {
            error = $"geçersiz section_id: {sectionId}";
            return false;
        }

        // K2: section_id = /about anchor'ı; ayrışan anchor kaynak bağlantısını kırar.
        if (!string.Equals(ReadString(section, "anchor"), sectionId, StringComparison.Ordinal))
        {
            error = $"bölüm anchor'ı section_id ile aynı olmalıdır: {sectionId}";
            return false;
        }

        var body = ReadString(section, "body");
        var kind = ReadString(section, "kind");
        if (body is null || kind is null)
        {
            error = $"bölüm body/kind eksik: {sectionId}";
            return false;
        }

        if (!section.TryGetProperty("title", out var title) || title.ValueKind != JsonValueKind.Object
            || ReadString(title, "tr") is not { } titleTr || ReadString(title, "en") is not { } titleEn)
        {
            error = $"bölüm title.tr/title.en eksik: {sectionId}";
            return false;
        }

        AuthorProfileClaim claim = new(null, null, null, null, null);
        if (section.TryGetProperty("claim", out var claimElement) && claimElement.ValueKind == JsonValueKind.Object)
        {
            claim = new AuthorProfileClaim(
                ReadString(claimElement, "kind"),
                ReadString(claimElement, "as_of"),
                ReadString(claimElement, "temporal"),
                ReadString(claimElement, "status"),
                ReadString(claimElement, "date_precision"));
        }

        var retrievable = !section.TryGetProperty("retrievable", out var retrievableElement)
                          || retrievableElement.ValueKind != JsonValueKind.False;

        parsed = new AuthorProfileSection(
            sectionId,
            sectionId,
            kind,
            StringList(section, "heading_path"),
            new AuthorProfileLocalizedText(titleTr, titleEn),
            body,
            StringList(section, "notes"),
            claim,
            retrievable);
        return true;
    }

    private static string? ReadString(JsonElement element, string name) =>
        element.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.String
            ? value.GetString()
            : null;

    private static IReadOnlyList<string> StringList(JsonElement element, string name) =>
        element.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.Array
            ? value.EnumerateArray()
                .Where(item => item.ValueKind == JsonValueKind.String)
                .Select(item => item.GetString()!)
                .ToList()
            : [];

    private static ReadOnlyMemory<byte> StripBom(byte[] bytes) =>
        bytes is [0xEF, 0xBB, 0xBF, ..] ? bytes.AsMemory(3) : bytes;
}
