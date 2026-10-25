using System.Diagnostics;
using OpenTelemetry;

namespace BlogApp.Presentation.Api.Services;

/// <summary>Retain bounded operational dimensions and remove content-bearing tags.</summary>
internal sealed class AgentTelemetryPrivacyProcessor : BaseProcessor<Activity>
{
    private static readonly HashSet<string> AllowedTags = new(StringComparer.Ordinal)
    {
        "agent.mode", "agent.operation", "agent.status", "error.type",
        "http.request.method", "http.response.status_code", "http.route",
        "network.protocol.name", "network.protocol.version",
        "db.system", "db.system.name", "db.operation.name",
        "messaging.system", "messaging.operation.name",
    };

    public override void OnEnd(Activity activity)
    {
        // Activity events are immutable and can contain exception bodies. Drop
        // such spans before the export processor rather than pretending that
        // tag filtering can sanitize their event payloads.
        if (activity.Events.Any())
        {
            activity.ActivityTraceFlags &= ~ActivityTraceFlags.Recorded;
            return;
        }
        foreach (var tag in activity.TagObjects.ToArray())
            if (!AllowedTags.Contains(tag.Key)) activity.SetTag(tag.Key, null);
        // Exception messages can also be carried outside the tag collection.
        activity.SetStatus(activity.Status);
    }
}
