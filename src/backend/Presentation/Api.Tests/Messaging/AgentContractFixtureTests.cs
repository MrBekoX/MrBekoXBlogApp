using System.Text.Json;
using System.Text.Json.Nodes;
using BlogApp.Core.Application.Common.Messaging;
using BlogApp.Core.Application.Common.Options;
using Xunit;

namespace BlogApp.Presentation.Api.Tests.Messaging;

/// <summary>
/// Ortak fixture setlerinin (.NET + Python aynı dosyalar) .NET doğrulayıcı üzerinden akışı:
/// v1 (fixtures/manifest.json) ve v2 (fixtures/v2/manifest.json) manifest'lerindeki her case için
/// beklenti (valid / kategori) doğrulanır. schema_expect=skip case'leri yalnız doğrulayıcının
/// çapraz kurallarıyla yakalanır (profile source_id/url, citation↔snapshot, v2'de olmayan tür).
/// </summary>
public sealed class AgentContractFixtureTests
{
    private const int UnsupportedVersionProbe = 99;

    public static TheoryData<string> FixtureCases()
    {
        var data = new TheoryData<string>();
        foreach (var path in LoadManifest(1).Select(c => c.File))
        {
            data.Add(path);
        }

        return data;
    }

    public static TheoryData<string> V2FixtureCases()
    {
        var data = new TheoryData<string>();
        foreach (var path in LoadManifest(2).Select(c => c.File))
        {
            data.Add(path);
        }

        return data;
    }

    [Theory]
    [MemberData(nameof(FixtureCases))]
    public void Fixture_Matches_Expectation(string relativePath) => AssertFixture(1, relativePath);

    [Theory]
    [MemberData(nameof(V2FixtureCases))]
    public void V2_Fixture_Matches_Expectation(string relativePath) => AssertFixture(2, relativePath);

    [Theory]
    [InlineData(1)]
    [InlineData(2)]
    public void Manifest_Covers_Every_Message_Type_With_A_Valid_Fixture(int version)
    {
        var validTypes = LoadManifest(version)
            .Where(c => c.Expect == "valid")
            .Select(c => c.MessageType!)
            .ToHashSet(StringComparer.Ordinal);

        var missing = AgentMessageTypeRegistry.MessageTypesFor(version)
            .Where(s => !validTypes.Contains(s.MessageType))
            .Select(s => s.MessageType)
            .ToList();

        Assert.True(missing.Count == 0, $"v{version} geçerli fixture'ı olmayan mesaj türleri: {string.Join(", ", missing)}");
    }

    [Theory]
    [InlineData(1)]
    [InlineData(2)]
    public void Registry_Covers_Every_Contract_Message_Type(int version)
    {
        var contract = JsonDocument.Parse(File.ReadAllText(Path.Combine(ContractPaths.VersionDirectory(version), "contract.json")));
        var contractTypes = contract.RootElement.GetProperty("message_types").EnumerateObject().Select(p => p.Name).ToHashSet();

        var registryTypes = AgentMessageTypeRegistry.MessageTypesFor(version).Select(s => s.MessageType).ToHashSet();

        Assert.True(contractTypes.SetEquals(registryTypes),
            $"v{version} contract.json ile registry aynı tür kümesini kapsamalıdır; fark: {string.Join(", ", contractTypes.Except(registryTypes).Concat(registryTypes.Except(contractTypes)))}");
    }

    [Theory]
    [InlineData(0)]
    [InlineData(3)]
    [InlineData(99)]
    [InlineData(int.MaxValue)]
    public void Any_Unsupported_Version_Is_Classified_Unknown_Version(int version)
    {
        foreach (var file in (string[])["valid/agent.execute.requested.json", "valid/agent.run.completed.json"])
        {
            var node = JsonNode.Parse(File.ReadAllText(Path.Combine(ContractPaths.FixturesDirectory, file)))!.AsObject();
            node["schema_version"] = version;

            var result = new AgentContractValidator().Validate(node.ToJsonString());

            Assert.False(result.IsValid);
            Assert.Equal(AgentContractErrorCategory.UnknownVersion, result.Error!.Category);
        }
    }

    [Fact]
    public void Typed_Validation_Materializes_Strongly_Typed_Payload()
    {
        var json = File.ReadAllText(Path.Combine(ContractPaths.FixturesDirectory, "valid", "agent.execute.requested.with_article.json"));
        var validator = new AgentContractValidator();

        var ok = validator.TryValidateAs<AgentExecutionRequestedV1>(json, out var envelope, out var payload, out var error);

        Assert.True(ok, error?.ToString());
        Assert.Equal("user-42", envelope!.RunId is not null ? payload!.UserRef : null);
        Assert.Equal("my-blog-post", payload!.ArticleId);
        Assert.Equal(7, payload.ArticleRevision);
        Assert.Equal(2, payload.ConversationHistory!.Count);
    }

    [Fact]
    public void Typed_Validation_Selects_V2_Dto_By_Version()
    {
        var json = File.ReadAllText(Path.Combine(ContractPaths.V2FixturesDirectory, "valid", "agent.execute.requested.who_am_i.json"));
        var validator = new AgentContractValidator();

        Assert.False(validator.TryValidateAs<AgentExecutionRequestedV1>(json, out _, out _, out var wrongDto));
        Assert.Equal(AgentContractErrorCategory.WrongType, wrongDto!.Category);

        var ok = validator.TryValidateAs<AgentExecutionRequestedV2>(json, out var envelope, out var payload, out var error);
        Assert.True(ok, error?.ToString());
        Assert.Equal(2, envelope!.SchemaVersion);
        Assert.Equal("who_am_i", payload!.ConversationTopic);
        Assert.Equal("berkay-kaplan", payload.ProfileSnapshot!.ProfileId);
        Assert.Null(payload.ArticleId);
    }

    [Fact]
    public void Typed_Validation_Materializes_V2_Profile_Citation()
    {
        var json = File.ReadAllText(Path.Combine(ContractPaths.V2FixturesDirectory, "valid", "agent.run.completed.profile.json"));

        var ok = new AgentContractValidator().TryValidateAs<AgentRunCompletedV2>(json, out _, out var payload, out var error);

        Assert.True(ok, error?.ToString());
        Assert.Equal("profile", payload!.RunIntent);
        var citation = Assert.Single(payload.Citations!);
        Assert.Equal("profile", citation.Kind);
        Assert.Equal("education", citation.SectionId);
        Assert.Equal("/about#education", citation.Url);
        Assert.True(payload.ProfileSnapshot!.SameAs(new AgentProfileSnapshotRef
        {
            ProfileId = citation.ProfileId!,
            Revision = citation.ProfileRevision!.Value,
            ContentHash = citation.ProfileContentHash!,
        }));
    }

    [Fact]
    public void Typed_Validation_Rejects_Unknown_Payload_Fields()
    {
        var json = File.ReadAllText(Path.Combine(ContractPaths.FixturesDirectory, "invalid", "extra_payload_field.json"));
        var validator = new AgentContractValidator();

        var ok = validator.TryValidateAs<AgentExecutionRequestedV1>(json, out _, out _, out var error);

        Assert.False(ok);
        Assert.Equal(AgentContractErrorCategory.ExtraField, error!.Category);
    }

    [Fact]
    public void Size_Gate_Applies_Configured_Limit_Before_Parsing()
    {
        var json = File.ReadAllText(Path.Combine(ContractPaths.FixturesDirectory, "valid", "agent.execute.requested.json"));
        var validator = new AgentContractValidator(new AgentMessagingSettings { MaxPayloadBytes = 32 });

        var result = validator.Validate(json);

        Assert.False(result.IsValid);
        Assert.Equal(AgentContractErrorCategory.Oversized, result.Error!.Category);
    }

    // ------------------------------------------------------------------ yardımcılar

    private static void AssertFixture(int version, string relativePath)
    {
        var manifestCase = LoadManifest(version).Single(c => c.File == relativePath);
        var json = File.ReadAllText(Path.Combine(
            ContractPaths.FixturesDirectoryFor(version), relativePath.Replace('/', Path.DirectorySeparatorChar)));

        // unknown_version case'i geçiş döneminde desteklenen bir sürüm taşıyabilir (v1 manifest'teki
        // eski "schema_version: 2" fixture'ı K3 ile 99'a çekilir). Sürüm artık destekleniyorsa
        // case'in niyeti (desteklenmeyen sürüm) desteklenmeyen bir sürümle korunur.
        if (manifestCase.Reason == "unknown_version")
        {
            var node = JsonNode.Parse(json)!.AsObject();
            if (node["schema_version"] is JsonValue versionValue
                && versionValue.TryGetValue<int>(out var fixtureVersion)
                && AgentMessageTypeRegistry.IsSupportedVersion(fixtureVersion))
            {
                node["schema_version"] = UnsupportedVersionProbe;
                json = node.ToJsonString();
            }
        }

        var result = new AgentContractValidator().Validate(json);

        if (manifestCase.Expect == "valid")
        {
            Assert.True(result.IsValid, $"v{version} {relativePath} geçerli beklenirken reddedildi: {result.Error}");
            Assert.Equal(manifestCase.MessageType, result.Envelope!.MessageType);
            Assert.Equal(version, result.Envelope.SchemaVersion);
            Assert.NotNull(result.PayloadNode);
            return;
        }

        Assert.False(result.IsValid, $"v{version} {relativePath} geçersiz beklenirken kabul edildi");
        var expectedCategory = ParseCategory(manifestCase.Reason!);
        Assert.True(result.Error is not null, $"v{version} {relativePath} için hata beklenirken boş döndü");
        Assert.True(expectedCategory == result.Error!.Category,
            $"v{version} {relativePath}: beklenen kategori {expectedCategory}, gelen {result.Error.Category} ({result.Error.Field}: {result.Error.Message})");
    }

    private static List<ManifestEntry> LoadManifest(int version)
    {
        var manifestPath = Path.Combine(ContractPaths.FixturesDirectoryFor(version), "manifest.json");
        using var doc = JsonDocument.Parse(File.ReadAllText(manifestPath));
        return doc.RootElement.GetProperty("cases").EnumerateArray()
            .Select(e => new ManifestEntry(
                e.GetProperty("file").GetString()!,
                e.GetProperty("expect").GetString()!,
                e.TryGetProperty("reason", out var reason) ? reason.GetString() : null,
                e.TryGetProperty("message_type", out var type) ? type.GetString() : null))
            .ToList();
    }

    private static AgentContractErrorCategory ParseCategory(string reason) => reason switch
    {
        "missing_field" => AgentContractErrorCategory.MissingField,
        "unknown_version" => AgentContractErrorCategory.UnknownVersion,
        "unknown_type" => AgentContractErrorCategory.UnknownType,
        "oversized" => AgentContractErrorCategory.Oversized,
        "wrong_type" => AgentContractErrorCategory.WrongType,
        "bad_format" => AgentContractErrorCategory.BadFormat,
        "extra_field" => AgentContractErrorCategory.ExtraField,
        "producer_mismatch" => AgentContractErrorCategory.ProducerMismatch,
        _ => throw new InvalidOperationException($"Bilinmeyen kategori: {reason}")
    };

    private sealed record ManifestEntry(string File, string Expect, string? Reason, string? MessageType);
}
