using System.Globalization;
using System.Text.Json;
using BlogApp.Core.Application.Common.Messaging;

namespace BlogApp.Core.Application.Features.AgentFeature.Services;

/// <summary>Konu değerleri (API: conversationTopic, wire v2: conversation_topic; K1).</summary>
public static class AgentConversationTopics
{
    public const string Auto = "auto";
    public const string WhoAmI = "who_am_i";

    public static bool IsKnown(string? topic) => topic is Auto or WhoAmI;

    /// <summary>İstemci değerini normalize eder: boş → auto; aksi halde trim + küçük harf
    /// (bilinmeyen değer korunur ve doğrulayıcıda reddedilir).</summary>
    public static string Normalize(string? topic) =>
        string.IsNullOrWhiteSpace(topic) ? Auto : topic.Trim().ToLowerInvariant();
}

/// <summary>ContextSnapshotJson anahtarları (K6). Değerler string olarak saklanır
/// (snapshot Dictionary&lt;string, string?&gt; serileştirmesidir).</summary>
public static class AgentRunContextKeys
{
    public const string WireVersion = "wire_version";
    public const string ConversationTopic = "conversation_topic";
    public const string ProfileId = "profile_id";
    public const string ProfileRevision = "profile_revision";
    public const string ProfileContentHash = "profile_content_hash";
    public const string ProfileCapability = "profile_capability";

    public const string CapabilityAvailable = "available";
    public const string CapabilityUnavailable = "unavailable";
}

/// <summary>
/// Kalıcı run bağlamının wire/konu/profil görünümü (ContextSnapshotJson; migration yok).
/// Eski kayıtlar: eksik konu = auto, eksik sürüm = 1 (K6). Bozuk/eksik değerler güvenli
/// varsayılana düşer (v1 + auto + pinsiz profil) — v1 run'ları eski akışta kalır.
/// </summary>
public sealed record AgentRunWireContext(
    int WireVersion,
    string ConversationTopic,
    AgentProfileSnapshotRef? PinnedProfile,
    string? ProfileCapability)
{
    public static readonly AgentRunWireContext Legacy =
        new(AgentMessageTypeRegistry.V1, AgentConversationTopics.Auto, null, null);

    public bool IsWhoAmI => ConversationTopic == AgentConversationTopics.WhoAmI;

    public bool IsV2 => WireVersion >= AgentMessageTypeRegistry.V2;

    public static AgentRunWireContext Parse(string? contextSnapshotJson)
    {
        if (string.IsNullOrWhiteSpace(contextSnapshotJson))
        {
            return Legacy;
        }

        try
        {
            using var document = JsonDocument.Parse(contextSnapshotJson);
            var root = document.RootElement;
            if (root.ValueKind != JsonValueKind.Object)
            {
                return Legacy;
            }

            var version = ReadInt(root, AgentRunContextKeys.WireVersion) is { } parsedVersion
                          && AgentMessageTypeRegistry.IsSupportedVersion(parsedVersion)
                ? parsedVersion
                : AgentMessageTypeRegistry.V1;

            var topic = ReadString(root, AgentRunContextKeys.ConversationTopic);
            topic = AgentConversationTopics.IsKnown(topic) ? topic! : AgentConversationTopics.Auto;

            AgentProfileSnapshotRef? pinned = null;
            var profileId = ReadString(root, AgentRunContextKeys.ProfileId);
            var revision = ReadInt(root, AgentRunContextKeys.ProfileRevision);
            var hash = ReadString(root, AgentRunContextKeys.ProfileContentHash);
            if (profileId is not null && AgentContractFormats.IsValidProfileId(profileId)
                && revision is >= 1
                && hash is not null && AgentContractFormats.IsValidHashHex(hash))
            {
                pinned = new AgentProfileSnapshotRef { ProfileId = profileId, Revision = revision.Value, ContentHash = hash };
            }

            return new AgentRunWireContext(version, topic, pinned, ReadString(root, AgentRunContextKeys.ProfileCapability));
        }
        catch (JsonException)
        {
            return Legacy;
        }
    }

    private static string? ReadString(JsonElement root, string key) =>
        root.TryGetProperty(key, out var value) && value.ValueKind == JsonValueKind.String
            ? value.GetString()
            : null;

    private static int? ReadInt(JsonElement root, string key)
    {
        if (!root.TryGetProperty(key, out var value))
        {
            return null;
        }

        return value.ValueKind switch
        {
            JsonValueKind.Number when value.TryGetInt32(out var number) => number,
            JsonValueKind.String when int.TryParse(value.GetString(), NumberStyles.None, CultureInfo.InvariantCulture, out var text) => text,
            _ => null,
        };
    }
}
