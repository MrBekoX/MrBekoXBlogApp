using System.Text.Json;
using BlogApp.Core.Application.Common.Messaging;
using BlogApp.Core.Application.Common.Options;
using Xunit;

namespace BlogApp.Presentation.Api.Tests.Messaging;

/// <summary>
/// Şema aynası: contract.json + JSON Schema dosyaları ile .NET registry/kuralları aynı sözleşmeyi
/// tanımlamalıdır. .NET tarafı şema motoru kullanmaz; bu testler yansımanın denkliğini sabitler.
/// </summary>
public sealed class AgentContractSchemaMirrorTests
{
    [Fact]
    public void Envelope_Schema_Matches_Registry_Rules()
    {
        var schema = ReadJson(Path.Combine(ContractPaths.V1Directory, "envelope.schema.json"));

        Assert.Equal(false, schema.GetProperty("additionalProperties").GetBoolean());

        var required = schema.GetProperty("required").EnumerateArray().Select(v => v.GetString()!).ToHashSet();
        var registryRequired = AgentContractValidator.EnvelopeFieldRules.Where(f => f.Required).Select(f => f.Name).ToHashSet();
        Assert.True(required.SetEquals(registryRequired),
            $"zarf required farkı: şema=[{string.Join(",", required)}] registry=[{string.Join(",", registryRequired)}]");

        var properties = schema.GetProperty("properties");
        foreach (var field in AgentContractValidator.EnvelopeFieldRules)
        {
            Assert.True(properties.TryGetProperty(field.Name, out _), $"zarf şemasında {field.Name} yok");
            if (field.EnumValues is not null)
            {
                var schemaEnum = properties.GetProperty(field.Name).GetProperty("enum")
                    .EnumerateArray().Select(v => v.GetString()!).ToList();
                Assert.True(schemaEnum.SequenceEqual(field.EnumValues), $"zarf {field.Name} enum farkı");
            }
        }
    }

    [Fact]
    public void Payload_Schemas_Match_Registry_Rules()
    {
        foreach (var spec in AgentMessageTypeRegistry.MessageTypes)
        {
            var schema = ReadJson(Path.Combine(ContractPaths.V1Directory, spec.PayloadSchema.Replace('/', Path.DirectorySeparatorChar)));
            Assert.Equal(false, schema.GetProperty("additionalProperties").GetBoolean());

            var required = schema.TryGetProperty("required", out var requiredArray)
                ? requiredArray.EnumerateArray().Select(v => v.GetString()!).ToHashSet()
                : new HashSet<string>();
            var registryRequired = spec.PayloadFields.Where(f => f.Required).Select(f => f.Name).ToHashSet();
            Assert.True(required.SetEquals(registryRequired),
                $"{spec.MessageType} required farkı: şema=[{string.Join(",", required)}] registry=[{string.Join(",", registryRequired)}]");

            var properties = schema.GetProperty("properties");
            foreach (var field in spec.PayloadFields)
            {
                Assert.True(properties.TryGetProperty(field.Name, out var property), $"{spec.MessageType} şemasında {field.Name} yok");
                if (field.EnumValues is not null)
                {
                    var schemaEnum = ResolveEnumValues(property);
                    Assert.True(schemaEnum is not null,
                        $"{spec.MessageType}.{field.Name} şemasında enum bulunamadı");
                    Assert.True(schemaEnum!.SequenceEqual(field.EnumValues), $"{spec.MessageType}.{field.Name} enum farkı");
                }
            }
        }
    }

    [Fact]
    public void Contract_Routing_Matches_Registry()
    {
        var contract = ReadJson(Path.Combine(ContractPaths.V1Directory, "contract.json"));

        Assert.Equal(1, contract.GetProperty("version").GetInt32());
        Assert.Equal(AgentMessageTypeRegistry.ContentType, contract.GetProperty("content_type").GetString());
        Assert.Equal(new AgentMessagingSettings().MaxPayloadBytes, contract.GetProperty("max_payload_bytes").GetInt32());

        var contractProducers = contract.GetProperty("producers").EnumerateArray().Select(v => v.GetString()!).ToList();
        Assert.Equal(AgentMessageTypeRegistry.AllProducers, contractProducers);

        var messageTypes = contract.GetProperty("message_types");
        Assert.Equal(AgentMessageTypeRegistry.MessageTypes.Count, messageTypes.EnumerateObject().Count());

        foreach (var spec in AgentMessageTypeRegistry.MessageTypes)
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

            Assert.Equal(spec.RoutingKey, $"{spec.MessageType}.v1");
        }
    }

    private static JsonElement ReadJson(string path)
    {
        using var doc = JsonDocument.Parse(File.ReadAllText(path));
        return doc.RootElement.Clone();
    }

    /// <summary>Özellikteki enum değerlerini döndürür; $ref common.schema.json $defs'e çözümlenir.</summary>
    private static List<string>? ResolveEnumValues(JsonElement property)
    {
        if (property.TryGetProperty("enum", out var inline))
        {
            return inline.EnumerateArray().Select(v => v.GetString()!).ToList();
        }

        if (property.TryGetProperty("$ref", out var reference)
            && reference.GetString() is { } refUri
            && refUri.StartsWith("urn:blog-agent:v1:common#/$defs/", StringComparison.Ordinal))
        {
            var defName = refUri["urn:blog-agent:v1:common#/$defs/".Length..];
            var common = ReadJson(Path.Combine(ContractPaths.V1Directory, "common.schema.json"));
            var def = common.GetProperty("$defs").GetProperty(defName);
            if (def.TryGetProperty("enum", out var defEnum))
            {
                return defEnum.EnumerateArray().Select(v => v.GetString()!).ToList();
            }
        }

        return null;
    }
}
