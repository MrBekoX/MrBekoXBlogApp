using System.Reflection;
using System.Text.Json;
using System.Text.Json.Serialization;
using BlogApp.Core.Application.Common.Messaging;
using BlogApp.Core.Application.Common.Options;
using Xunit;

namespace BlogApp.Presentation.Api.Tests.Messaging;

/// <summary>
/// Şema aynası: her sözleşme sürümü için contract.json + JSON Schema dosyaları ile .NET
/// registry/kuralları aynı sözleşmeyi tanımlamalıdır. .NET tarafı şema motoru kullanmaz; bu testler
/// yansımanın denkliğini (sürüm başına) sabitler — iç içe nesneler (usage, citations[], profile_snapshot,
/// conversation_history[]) ve iç içe enum'lar (citation kind) dahil.
/// </summary>
public sealed class AgentContractSchemaMirrorTests
{
    public static TheoryData<int> Versions() => new() { 1, 2 };

    [Fact]
    public void Registry_Supports_Exactly_Versions_One_And_Two()
    {
        Assert.Equal([1, 2], AgentMessageTypeRegistry.SupportedVersions);
        Assert.False(AgentMessageTypeRegistry.IsSupportedVersion(0));
        Assert.False(AgentMessageTypeRegistry.IsSupportedVersion(3));
        Assert.False(AgentMessageTypeRegistry.IsSupportedVersion(99));
        Assert.Empty(AgentMessageTypeRegistry.MessageTypesFor(99));
    }

    [Theory]
    [MemberData(nameof(Versions))]
    public void Envelope_Schema_Matches_Registry_Rules(int version)
    {
        var schema = ReadJson(Path.Combine(ContractPaths.VersionDirectory(version), "envelope.schema.json"));

        Assert.Equal(false, schema.GetProperty("additionalProperties").GetBoolean());

        var required = schema.GetProperty("required").EnumerateArray().Select(v => v.GetString()!).ToHashSet();
        var registryRequired = AgentContractValidator.EnvelopeFieldRules.Where(f => f.Required).Select(f => f.Name).ToHashSet();
        Assert.True(required.SetEquals(registryRequired),
            $"v{version} zarf required farkı: şema=[{string.Join(",", required)}] registry=[{string.Join(",", registryRequired)}]");

        var properties = schema.GetProperty("properties");
        Assert.Equal(version, properties.GetProperty("schema_version").GetProperty("const").GetInt32());
        foreach (var field in AgentContractValidator.EnvelopeFieldRules)
        {
            Assert.True(properties.TryGetProperty(field.Name, out _), $"v{version} zarf şemasında {field.Name} yok");
            if (field.EnumValues is not null)
            {
                var schemaEnum = properties.GetProperty(field.Name).GetProperty("enum")
                    .EnumerateArray().Select(v => v.GetString()!).ToList();
                Assert.True(schemaEnum.SequenceEqual(field.EnumValues), $"v{version} zarf {field.Name} enum farkı");
            }
        }

        var schemaProperties = properties.EnumerateObject().Select(p => p.Name).ToHashSet();
        Assert.True(schemaProperties.SetEquals(AgentContractValidator.EnvelopeFieldRules.Select(f => f.Name)),
            $"v{version} zarf alan kümesi farkı");
    }

    [Theory]
    [MemberData(nameof(Versions))]
    public void Payload_Schemas_Match_Registry_Rules(int version)
    {
        foreach (var spec in AgentMessageTypeRegistry.MessageTypesFor(version))
        {
            Assert.Equal(version, spec.SchemaVersion);
            var schema = ReadJson(Path.Combine(
                ContractPaths.VersionDirectory(version), spec.PayloadSchema.Replace('/', Path.DirectorySeparatorChar)));
            AssertObjectMirrors($"v{version} {spec.MessageType}", schema, spec.PayloadFields, version);
        }
    }

    [Theory]
    [MemberData(nameof(Versions))]
    public void Contract_Routing_Matches_Registry(int version)
    {
        var contract = ReadJson(Path.Combine(ContractPaths.VersionDirectory(version), "contract.json"));

        Assert.Equal(version, contract.GetProperty("version").GetInt32());
        Assert.Equal(AgentMessageTypeRegistry.ContentType, contract.GetProperty("content_type").GetString());
        Assert.Equal(new AgentMessagingSettings().MaxPayloadBytes, contract.GetProperty("max_payload_bytes").GetInt32());

        var contractProducers = contract.GetProperty("producers").EnumerateArray().Select(v => v.GetString()!).ToList();
        Assert.Equal(AgentMessageTypeRegistry.AllProducers, contractProducers);

        var messageTypes = contract.GetProperty("message_types");
        var specs = AgentMessageTypeRegistry.MessageTypesFor(version);
        Assert.Equal(specs.Count, messageTypes.EnumerateObject().Count());

        foreach (var spec in specs)
        {
            var entry = messageTypes.GetProperty(spec.MessageType);
            Assert.Equal(spec.Exchange, entry.GetProperty("exchange").GetString());
            Assert.Equal(spec.RoutingKey, entry.GetProperty("routing_key").GetString());
            Assert.Equal(spec.PayloadSchema, entry.GetProperty("payload_schema").GetString());
            Assert.Equal(spec.RequiresRunIdentity, entry.GetProperty("requires_run_identity").GetBoolean());
            Assert.Equal(spec.RequiresDeadline, entry.GetProperty("requires_deadline").GetBoolean());

            var expectedDirection = spec.Direction == AgentMessageDirection.BackendToAgent ? "backend_to_agent" : "agent_to_backend";
            Assert.Equal(expectedDirection, entry.GetProperty("direction").GetString());

            var producers = entry.GetProperty("allowed_producers").EnumerateArray().Select(v => v.GetString()!).ToList();
            Assert.Equal(spec.AllowedProducers, producers);

            // Routing key kuralı: "{tür}.v{sürüm}" — outbox routing key'leri registry'den türetilir.
            Assert.Equal($"{spec.MessageType}.v{version}", spec.RoutingKey);
            Assert.Equal(spec.RoutingKey, AgentMessageTypeRegistry.RoutingKeyFor(version, spec.MessageType));
        }
    }

    [Fact]
    public void V2_Contains_Only_The_Thirteen_Run_Scoped_Types()
    {
        var v1RunTypes = AgentMessageTypeRegistry.MessageTypesFor(1)
            .Where(s => s.RequiresRunIdentity)
            .Select(s => s.MessageType)
            .ToHashSet();
        var v2Types = AgentMessageTypeRegistry.MessageTypesFor(2).Select(s => s.MessageType).ToHashSet();

        Assert.Equal(13, v2Types.Count);
        Assert.True(v1RunTypes.SetEquals(v2Types));
        Assert.DoesNotContain(v2Types, t => t.StartsWith("content.", StringComparison.Ordinal));
        Assert.False(AgentMessageTypeRegistry.TryGet(2, AgentMessageTypes.ProfileContentChanged, out _));
    }

    [Theory]
    [MemberData(nameof(Versions))]
    public void Citation_Kind_Enum_Mirrors_Common_Source_Reference(int version)
    {
        var common = ReadJson(Path.Combine(ContractPaths.VersionDirectory(version), "common.schema.json"));
        var schemaKinds = common.GetProperty("$defs").GetProperty("source_reference").GetProperty("properties")
            .GetProperty("kind").GetProperty("enum").EnumerateArray().Select(v => v.GetString()!).ToList();

        foreach (var type in (string[])[AgentMessageTypes.RunCompleted, AgentMessageTypes.RunPartiallyCompleted])
        {
            var spec = AgentMessageTypeRegistry.Get(version, type);
            var citationItem = spec.PayloadFields.Single(f => f.Name == "citations").Items!;
            var kindRule = citationItem.ObjectFields!.Single(f => f.Name == "kind");
            Assert.Equal(schemaKinds, kindRule.EnumValues);
        }

        Assert.Equal(version == 2, schemaKinds.Contains("profile"));
    }

    [Theory]
    [MemberData(nameof(Versions))]
    public void Payload_Dto_Properties_Mirror_Schema_Properties(int version)
    {
        foreach (var spec in AgentMessageTypeRegistry.MessageTypesFor(version))
        {
            var schema = ReadJson(Path.Combine(
                ContractPaths.VersionDirectory(version), spec.PayloadSchema.Replace('/', Path.DirectorySeparatorChar)));
            var schemaProperties = schema.GetProperty("properties").EnumerateObject().Select(p => p.Name).ToHashSet();
            var dtoProperties = JsonPropertyNames(spec.PayloadDtoType);
            Assert.True(schemaProperties.SetEquals(dtoProperties),
                $"v{version} {spec.MessageType} DTO ({spec.PayloadDtoType.Name}) alan farkı: "
                + $"şema=[{string.Join(",", schemaProperties.Except(dtoProperties))}] dto=[{string.Join(",", dtoProperties.Except(schemaProperties))}]");
        }
    }

    [Fact]
    public void V2_Source_Reference_Dto_Mirrors_Common_Schema()
    {
        var common = ReadJson(Path.Combine(ContractPaths.V2Directory, "common.schema.json"));
        var defs = common.GetProperty("$defs");
        Assert.True(defs.GetProperty("source_reference").GetProperty("properties").EnumerateObject()
            .Select(p => p.Name).ToHashSet().SetEquals(JsonPropertyNames(typeof(AgentSourceReferenceV2))));
        Assert.True(defs.GetProperty("profile_snapshot_ref").GetProperty("properties").EnumerateObject()
            .Select(p => p.Name).ToHashSet().SetEquals(JsonPropertyNames(typeof(AgentProfileSnapshotRef))));
    }

    // ------------------------------------------------------------------ yardımcılar

    private static void AssertObjectMirrors(string label, JsonElement schema, IReadOnlyList<AgentFieldRule> fields, int version)
    {
        Assert.Equal(false, schema.GetProperty("additionalProperties").GetBoolean());

        var required = schema.TryGetProperty("required", out var requiredArray)
            ? requiredArray.EnumerateArray().Select(v => v.GetString()!).ToHashSet()
            : new HashSet<string>();
        var registryRequired = fields.Where(f => f.Required).Select(f => f.Name).ToHashSet();
        Assert.True(required.SetEquals(registryRequired),
            $"{label} required farkı: şema=[{string.Join(",", required)}] registry=[{string.Join(",", registryRequired)}]");

        var properties = schema.GetProperty("properties");
        var schemaNames = properties.EnumerateObject().Select(p => p.Name).ToHashSet();
        Assert.True(schemaNames.SetEquals(fields.Select(f => f.Name)),
            $"{label} alan kümesi farkı: şema=[{string.Join(",", schemaNames)}] registry=[{string.Join(",", fields.Select(f => f.Name))}]");

        foreach (var field in fields)
        {
            var property = Resolve(properties.GetProperty(field.Name), version);
            if (field.EnumValues is not null)
            {
                var schemaEnum = ResolveEnumValues(property);
                Assert.True(schemaEnum is not null, $"{label}.{field.Name} şemasında enum bulunamadı");
                Assert.True(schemaEnum!.SequenceEqual(field.EnumValues), $"{label}.{field.Name} enum farkı");
            }

            if (field.Kind == AgentFieldKind.Array && field.Items?.ObjectFields is { } itemFields)
            {
                var items = Resolve(property.GetProperty("items"), version);
                AssertObjectMirrors($"{label}.{field.Name}[]", items, itemFields, version);
            }

            if (field.Kind == AgentFieldKind.Object && field.ObjectFields is { } objectFields)
            {
                AssertObjectMirrors($"{label}.{field.Name}", property, objectFields, version);
            }
        }
    }

    /// <summary>$ref common.schema.json $defs'e (sürümün kendi common'ına) çözümlenir.</summary>
    private static JsonElement Resolve(JsonElement property, int version)
    {
        var prefix = $"urn:blog-agent:v{version}:common#/$defs/";
        if (property.TryGetProperty("$ref", out var reference)
            && reference.GetString() is { } refUri
            && refUri.StartsWith(prefix, StringComparison.Ordinal))
        {
            var common = ReadJson(Path.Combine(ContractPaths.VersionDirectory(version), "common.schema.json"));
            return common.GetProperty("$defs").GetProperty(refUri[prefix.Length..]);
        }

        if (property.TryGetProperty("$ref", out var localReference)
            && localReference.GetString() is { } localUri
            && localUri.StartsWith("#/$defs/", StringComparison.Ordinal))
        {
            var common = ReadJson(Path.Combine(ContractPaths.VersionDirectory(version), "common.schema.json"));
            return common.GetProperty("$defs").GetProperty(localUri["#/$defs/".Length..]);
        }

        return property;
    }

    private static List<string>? ResolveEnumValues(JsonElement property) =>
        property.TryGetProperty("enum", out var inline)
            ? inline.EnumerateArray().Select(v => v.GetString()!).ToList()
            : null;

    private static HashSet<string> JsonPropertyNames(Type dtoType) =>
        dtoType.GetProperties(BindingFlags.Public | BindingFlags.Instance)
            .Where(p => p.GetCustomAttribute<JsonExtensionDataAttribute>() is null)
            .Select(p => p.GetCustomAttribute<JsonPropertyNameAttribute>()?.Name)
            .Where(name => name is not null)
            .Select(name => name!)
            .ToHashSet();

    private static JsonElement ReadJson(string path)
    {
        using var doc = JsonDocument.Parse(File.ReadAllText(path));
        return doc.RootElement.Clone();
    }
}
