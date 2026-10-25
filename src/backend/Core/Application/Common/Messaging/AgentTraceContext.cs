using System.Diagnostics;

namespace BlogApp.Core.Application.Common.Messaging;

internal static class AgentTraceContext
{
    // Propagate only the validated W3C parent, never auth or arbitrary baggage.
    internal static string? Capture() =>
        Activity.Current is { IdFormat: ActivityIdFormat.W3C, Id: { } id }
        && AgentContractFormats.IsValidTraceParent(id) ? id : null;
}
