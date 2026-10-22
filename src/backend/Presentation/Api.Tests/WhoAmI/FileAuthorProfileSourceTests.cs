using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;
using BlogApp.Core.Application.Common.AuthorProfile;
using BlogApp.Infrastructure.Services.AuthorProfile;
using Xunit;

namespace BlogApp.Presentation.Api.Tests.WhoAmI;

/// <summary>
/// Canonical profil okuyucusu (K2, A22/A23/A33): build çıktısındaki kopya (cwd bağımsız) doğrulanır;
/// geçici dizin kopyalarında hash uyuşmazlığı, geri çekme, onaysızlık, eksik/bozuk dosya ve sürüm
/// güncellemesi (dosya damgası değişince yeniden doğrulama) senaryoları koşulur.
/// </summary>
public sealed class FileAuthorProfileSourceTests : IDisposable
{
    private static readonly string BuiltProfileDirectory =
        Path.Combine(AppContext.BaseDirectory, "content", "author-profile");

    private readonly List<string> _tempDirectories = [];

    public void Dispose()
    {
        foreach (var directory in _tempDirectories)
        {
            try
            {
                Directory.Delete(directory, recursive: true);
            }
            catch (IOException)
            {
                // geçici dizin temizliği best-effort
            }
        }
    }

    private string CreateCopy()
    {
        var directory = Path.Combine(Path.GetTempPath(), "author-profile-tests", Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(directory);
        File.Copy(Path.Combine(BuiltProfileDirectory, "manifest.json"), Path.Combine(directory, "manifest.json"));
        File.Copy(Path.Combine(BuiltProfileDirectory, "profile.json"), Path.Combine(directory, "profile.json"));
        _tempDirectories.Add(directory);
        return directory;
    }

    private static void EditManifest(string directory, Action<JsonObject> edit)
    {
        var path = Path.Combine(directory, "manifest.json");
        var manifest = JsonNode.Parse(File.ReadAllText(path, Encoding.UTF8))!.AsObject();
        edit(manifest);
        WriteAndTouch(path, Encoding.UTF8.GetBytes(manifest.ToJsonString()));
    }

    private static void WriteAndTouch(string path, byte[] bytes)
    {
        var previous = File.Exists(path) ? File.GetLastWriteTimeUtc(path) : DateTime.MinValue;
        File.WriteAllBytes(path, bytes);
        // Damga değişimini garanti et (aynı tick içinde ardışık yazımlar).
        File.SetLastWriteTimeUtc(path, (previous > DateTime.UtcNow ? previous : DateTime.UtcNow).AddSeconds(2));
    }

    private static string Sha256(byte[] bytes) => Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();

    [Fact]
    public void Default_Directory_Resolves_Under_Base_Directory_Not_Cwd()
    {
        Assert.Equal(Path.Combine(AppContext.BaseDirectory, "content", "author-profile"), FileAuthorProfileSource.ResolveDirectory(null));
        Assert.Equal(Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "data", "profile")),
            FileAuthorProfileSource.ResolveDirectory(Path.Combine("data", "profile")));
        var absolute = Path.Combine(Path.GetTempPath(), "x");
        Assert.Equal(absolute, FileAuthorProfileSource.ResolveDirectory(absolute));
    }

    [Fact]
    public void Built_Output_Copy_Is_Available_And_Hash_Matches_Manifest()
    {
        var source = new FileAuthorProfileSource(BuiltProfileDirectory);

        var state = source.GetCurrent();

        Assert.True(state.IsAvailable, state.Reason);
        var manifest = JsonNode.Parse(File.ReadAllText(Path.Combine(BuiltProfileDirectory, "manifest.json")))!.AsObject();
        Assert.Equal(manifest["content_hash"]!.GetValue<string>(), state.ActiveSnapshot!.ContentHash);
        Assert.Equal(Sha256(File.ReadAllBytes(Path.Combine(BuiltProfileDirectory, "profile.json"))), state.ActiveSnapshot.ContentHash);
        Assert.Equal("sample-author", state.ActiveSnapshot.ProfileId);
        Assert.Equal("Sample Author", state.Document!.OwnerName);
        Assert.Contains(state.Document.Sections, s => s.SectionId == "education" && s.Anchor == "education");
        Assert.All(state.Document.Sections, s => Assert.Equal(s.SectionId, s.Anchor));
        Assert.All(state.Document.ContactChannels, c => Assert.StartsWith("https://", c.Url));
        Assert.True(File.Exists(Path.Combine(BuiltProfileDirectory, "source", "author-profile.source.md")));
    }

    [Fact]
    public void Good_Copy_Is_Available_And_Cached_By_Stamp()
    {
        var source = new FileAuthorProfileSource(CreateCopy());

        var first = source.GetCurrent();
        var second = source.GetCurrent();

        Assert.True(first.IsAvailable, first.Reason);
        Assert.Same(first, second);
    }

    [Fact]
    public void Modified_Profile_Without_Manifest_Bump_Is_Hash_Mismatch()
    {
        var directory = CreateCopy();
        var source = new FileAuthorProfileSource(directory);
        Assert.True(source.GetCurrent().IsAvailable);

        var profilePath = Path.Combine(directory, "profile.json");
        var tampered = File.ReadAllText(profilePath, Encoding.UTF8).Replace("2000–2004", "2019–2024", StringComparison.Ordinal);
        WriteAndTouch(profilePath, Encoding.UTF8.GetBytes(tampered));

        var state = source.GetCurrent();
        Assert.Equal(AuthorProfileAvailability.HashMismatch, state.Availability);
        Assert.Null(state.Document);
        Assert.Null(state.ActiveSnapshot);
    }

    [Fact]
    public void New_Revision_Activates_After_Manifest_Is_Updated()
    {
        var directory = CreateCopy();
        var source = new FileAuthorProfileSource(directory);
        var before = source.GetCurrent().ActiveSnapshot!;

        var profilePath = Path.Combine(directory, "profile.json");
        var updated = Encoding.UTF8.GetBytes(File.ReadAllText(profilePath, Encoding.UTF8)
            .Replace("kurgusal bir yazılım", "güncellenmiş kurgusal bir yazılım", StringComparison.Ordinal));
        WriteAndTouch(profilePath, updated);
        EditManifest(directory, m =>
        {
            m["revision"] = before.Revision + 1;
            m["content_hash"] = Sha256(updated);
        });

        var after = source.GetCurrent();
        Assert.True(after.IsAvailable, after.Reason);
        Assert.Equal(before.Revision + 1, after.ActiveSnapshot!.Revision);
        Assert.NotEqual(before.ContentHash, after.ActiveSnapshot.ContentHash);
        Assert.False(after.ActiveSnapshot.Matches(before.ToRef()));
    }

    [Theory]
    [InlineData("status", "withdrawn")]
    [InlineData("approved", false)]
    public void Withdrawn_Or_Unapproved_Profile_Is_Not_Public(string field, object value)
    {
        var directory = CreateCopy();
        EditManifest(directory, m => m[field] = value switch
        {
            string text => JsonValue.Create(text),
            bool flag => JsonValue.Create(flag),
            _ => throw new InvalidOperationException(),
        });

        var state = new FileAuthorProfileSource(directory).GetCurrent();

        Assert.Equal(AuthorProfileAvailability.NotPublic, state.Availability);
        Assert.Null(state.Document);
    }

    [Fact]
    public void Missing_Directory_Or_Files_Are_Missing()
    {
        Assert.Equal(AuthorProfileAvailability.Missing,
            new FileAuthorProfileSource(Path.Combine(Path.GetTempPath(), "author-profile-tests", "yok-" + Guid.NewGuid().ToString("N"))).GetCurrent().Availability);

        var noProfile = CreateCopy();
        File.Delete(Path.Combine(noProfile, "profile.json"));
        Assert.Equal(AuthorProfileAvailability.Missing, new FileAuthorProfileSource(noProfile).GetCurrent().Availability);

        var noManifest = CreateCopy();
        File.Delete(Path.Combine(noManifest, "manifest.json"));
        Assert.Equal(AuthorProfileAvailability.Missing, new FileAuthorProfileSource(noManifest).GetCurrent().Availability);
    }

    [Fact]
    public void Corrupt_Manifest_Or_Foreign_Content_File_Is_Invalid()
    {
        var corrupt = CreateCopy();
        WriteAndTouch(Path.Combine(corrupt, "manifest.json"), Encoding.UTF8.GetBytes("{ bozuk"));
        Assert.Equal(AuthorProfileAvailability.Invalid, new FileAuthorProfileSource(corrupt).GetCurrent().Availability);

        var foreign = CreateCopy();
        EditManifest(foreign, m => m["content_file"] = "../secrets.json");
        Assert.Equal(AuthorProfileAvailability.Invalid, new FileAuthorProfileSource(foreign).GetCurrent().Availability);
    }

    [Fact]
    public void Profile_Id_Mismatch_Is_Invalid_Even_With_Matching_Hash()
    {
        var directory = CreateCopy();
        var profilePath = Path.Combine(directory, "profile.json");
        var changed = Encoding.UTF8.GetBytes(File.ReadAllText(profilePath, Encoding.UTF8)
            .Replace("\"profile_id\": \"sample-author\"", "\"profile_id\": \"someone-else\"", StringComparison.Ordinal));
        WriteAndTouch(profilePath, changed);
        EditManifest(directory, m => m["content_hash"] = Sha256(changed));

        var state = new FileAuthorProfileSource(directory).GetCurrent();

        Assert.Equal(AuthorProfileAvailability.Invalid, state.Availability);
    }
}
