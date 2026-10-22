using System.Text.Json;
using System.Text.Json.Nodes;
using BlogApp.Core.Application.Common.AuthorProfile;
using BlogApp.Core.Application.Common.Messaging;
using BlogApp.Core.Application.Features.AgentFeature.Services;

namespace BlogApp.Presentation.Api.Tests.WhoAmI;

/// <summary>Who am I testlerinin ortak verileri: pinlenmiş profil sürümü, run bağlamı ve v2
/// sonuç snapshot'ı kurucuları (DB/broker gerektirmez).</summary>
internal static class WhoAmITestData
{
    public const string ProfileId = "berkay-kaplan";
    public const string Hash = "4f3b02e187c2b8c04134aa2c80df4b2d8c817377780aca74d2a11e9bf0c1406d";
    public const string OtherHash = "2c26b46b68ffc68ff99b453c1d30413413422d706483bfa0f98a5e886266e7ae";

    public static AgentProfileSnapshotRef Snapshot(long revision = 1, string hash = Hash) =>
        new() { ProfileId = ProfileId, Revision = revision, ContentHash = hash };

    public static AuthorProfileSnapshot Active(long revision = 1, string hash = Hash) => new(ProfileId, revision, hash);

    /// <summary>Kabulde yazılan ContextSnapshotJson'un K6 anahtarları (değerler string).</summary>
    public static string ContextJson(int wireVersion, string topic, AgentProfileSnapshotRef? pinned = null, string? capability = null)
    {
        var snapshot = new Dictionary<string, string?>
        {
            ["question"] = "soru",
            [AgentRunContextKeys.WireVersion] = wireVersion.ToString(System.Globalization.CultureInfo.InvariantCulture),
            [AgentRunContextKeys.ConversationTopic] = topic,
            [AgentRunContextKeys.ProfileId] = pinned?.ProfileId,
            [AgentRunContextKeys.ProfileRevision] = pinned?.Revision.ToString(System.Globalization.CultureInfo.InvariantCulture),
            [AgentRunContextKeys.ProfileContentHash] = pinned?.ContentHash,
            [AgentRunContextKeys.ProfileCapability] = capability ?? (pinned is null ? null : "available"),
        };
        return JsonSerializer.Serialize(snapshot);
    }

    public static JsonObject ProfileCitation(string sectionId = "education", long chunk = 0, AgentProfileSnapshotRef? snapshot = null)
    {
        snapshot ??= Snapshot();
        return new JsonObject
        {
            ["kind"] = "profile",
            ["source_id"] = AgentContractFormats.ComposeProfileSourceId(
                snapshot.ProfileId, snapshot.Revision, snapshot.ContentHash, sectionId, chunk),
            ["title"] = "Eğitim",
            ["profile_id"] = snapshot.ProfileId,
            ["profile_revision"] = snapshot.Revision,
            ["profile_content_hash"] = snapshot.ContentHash,
            ["section_id"] = sectionId,
            ["chunk_index"] = chunk,
            ["url"] = AgentContractFormats.ComposeProfileUrl(sectionId),
        };
    }

    public static JsonObject ArticleCitation(Guid articleId) => new()
    {
        ["kind"] = "article",
        ["source_id"] = $"article:{articleId:D}:7:0",
        ["title"] = "Makale",
        ["article_id"] = articleId.ToString("D"),
        ["article_revision"] = 7,
        ["chunk_index"] = 0,
    };

    /// <summary>v2 completed/partial sonuç snapshot'ı (projection'ın ResultJson'a yazdığı payload).</summary>
    public static string ResultJson(
        string runIntent = "profile",
        string sourceScope = "profile",
        AgentProfileSnapshotRef? snapshot = null,
        IEnumerable<JsonObject>? citations = null,
        bool includeSnapshot = true,
        string answer = "Berkay Kaplan, Malatya Turgut Özal Üniversitesi'nde okudu.")
    {
        var payload = new JsonObject
        {
            ["event_sequence"] = 7,
            ["selected_mode"] = "fast",
            ["answer"] = answer,
            ["source_scope"] = sourceScope,
            ["run_intent"] = runIntent,
            ["usage"] = new JsonObject { ["run_id"] = Guid.NewGuid().ToString("D"), ["recorded_at"] = "2026-10-22T09:00:00Z" },
            ["citations"] = new JsonArray((citations ?? [ProfileCitation(snapshot: snapshot)]).Select(c => (JsonNode)c).ToArray()),
        };
        if (includeSnapshot)
        {
            var effective = snapshot ?? Snapshot();
            payload["profile_snapshot"] = new JsonObject
            {
                ["profile_id"] = effective.ProfileId,
                ["revision"] = effective.Revision,
                ["content_hash"] = effective.ContentHash,
            };
        }

        return payload.ToJsonString();
    }

    /// <summary>Test zarfı: verilen sürüm ve tür için run kimlikli zarf JSON'u.</summary>
    public static string Envelope(int version, string messageType, JsonObject payload, string producer = "agent-py", bool withDeadline = false)
    {
        var runId = "aaaaaaa1-0000-4000-8000-000000000001";
        if (payload["usage"] is JsonObject usage)
        {
            usage["run_id"] = runId;
        }

        var envelope = new JsonObject
        {
            ["message_id"] = "77777777-7777-4777-8777-777777777777",
            ["message_type"] = messageType,
            ["schema_version"] = version,
            ["run_id"] = runId,
            ["conversation_id"] = "bbbbbbb1-0000-4000-8000-000000000002",
            ["correlation_id"] = "ccccccc1-0000-4000-8000-000000000003",
            ["occurred_at"] = "2026-10-22T09:00:00Z",
            ["producer"] = producer,
            ["payload"] = payload,
        };
        if (withDeadline)
        {
            envelope["deadline_at"] = "2026-10-22T09:05:00Z";
        }

        return envelope.ToJsonString();
    }
}
