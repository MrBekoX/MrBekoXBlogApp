using System.Text.Json;
using BlogApp.Core.Application.Common.Messaging;
using BlogApp.Core.Application.Common.Options;
using Xunit;

namespace BlogApp.Presentation.Api.Tests.Messaging;

/// <summary>
/// Ortak fixture setinin (.NET + Python aynı dosyalar) .NET doğrulayıcı üzerinden akışı:
/// manifest'teki her case için beklenti (valid / kategori) kontrollü biçimde doğrulanır.
/// </summary>
public sealed class AgentContractFixtureTests
{
    public static TheoryData<string> FixtureCases()
    {
        var data = new TheoryData<string>();
        foreach (var path in LoadManifest().Select(c => c.File))
        {
            data.Add(path);
        }

        return data;
    }

    [Theory]
    [MemberData(nameof(FixtureCases))]
    public void Fixture_Matches_Expectation(string relativePath)
    {
        var manifestCase = ManifestCase(relativePath);
        var json = File.ReadAllText(Path.Combine(ContractPaths.FixturesDirectory, relativePath.Replace('/', Path.DirectorySeparatorChar)));
        var validator = new AgentContractValidator();
        var result = validator.Validate(json);

        if (manifestCase.Expect == "valid")
        {
            Assert.True(result.IsValid, $"{relativePath} geçerli beklenirken reddedildi: {result.Error}");
            Assert.Equal(manifestCase.MessageType, result.Envelope!.MessageType);
            Assert.NotNull(result.PayloadNode);
            return;
        }

        Assert.False(result.IsValid, $"{relativePath} geçersiz beklenirken kabul edildi");
        var expectedCategory = ParseCategory(manifestCase.Reason!);
        Assert.True(result.Error is not null, $"{relativePath} için hata beklenirken boş döndü");
        Assert.True(expectedCategory == result.Error!.Category,
            $"{relativePath}: beklenen kategori {expectedCategory}, gelen {result.Error.Category} ({result.Error.Message})");
    }

    [Fact]
    public void Manifest_Covers_Every_Message_Type_With_A_Valid_Fixture()
    {
        var validTypes = LoadManifest()
            .Where(c => c.Expect == "valid")
            .Select(c => c.MessageType!)
            .ToHashSet(StringComparer.Ordinal);

        var missing = AgentMessageTypeRegistry.MessageTypes
            .Where(s => !validTypes.Contains(s.MessageType))
            .Select(s => s.MessageType)
            .ToList();

        Assert.True(missing.Count == 0, $"Geçerli fixture'ı olmayan mesaj türleri: {string.Join(", ", missing)}");
    }

    [Fact]
    public void Registry_Covers_Every_Contract_Message_Type()
    {
        var contract = JsonDocument.Parse(File.ReadAllText(Path.Combine(ContractPaths.V1Directory, "contract.json")));
        var contractTypes = contract.RootElement.GetProperty("message_types").EnumerateObject().Select(p => p.Name).ToHashSet();

        var registryTypes = AgentMessageTypeRegistry.MessageTypes.Select(s => s.MessageType).ToHashSet();

        Assert.True(contractTypes.SetEquals(registryTypes),
            $"contract.json ile registry aynı tür kümesini kapsamalıdır; fark: {string.Join(", ", contractTypes.Except(registryTypes).Concat(registryTypes.Except(contractTypes)))}");
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

    private static List<ManifestEntry> LoadManifest()
    {
        var manifestPath = Path.Combine(ContractPaths.FixturesDirectory, "manifest.json");
        using var doc = JsonDocument.Parse(File.ReadAllText(manifestPath));
        return doc.RootElement.GetProperty("cases").EnumerateArray()
            .Select(e => new ManifestEntry(
                e.GetProperty("file").GetString()!,
                e.GetProperty("expect").GetString()!,
                e.TryGetProperty("reason", out var reason) ? reason.GetString() : null,
                e.TryGetProperty("message_type", out var type) ? type.GetString() : null))
            .ToList();
    }

    private static ManifestEntry ManifestCase(string relativePath) =>
        LoadManifest().Single(c => c.File == relativePath);

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
