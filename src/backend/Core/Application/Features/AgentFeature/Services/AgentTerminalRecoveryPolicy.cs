using System.Text.Json;
using BlogApp.Core.Application.Common.Options;
using BlogApp.Core.Domain.Entities;
using BlogApp.Core.Domain.Enums;
using Microsoft.EntityFrameworkCore;

namespace BlogApp.Core.Application.Features.AgentFeature.Services;

public sealed record AgentTerminalRecoveryState(bool IsProvisionalTerminal, DateTimeOffset? ReconciliationUntil,
    int ReconciliationRemainingSeconds = 0);

/// <summary>One bounded contract for timeout presentation and late-event admission.
/// A reaper closure does not fabricate a Python event sequence.</summary>
public static class AgentTerminalRecoveryPolicy
{
    public static bool IsBackendTimeout(AgentRun run)
    {
        if (run.Status != AgentRunStatus.Failed || string.IsNullOrWhiteSpace(run.ResultJson)) return false;
        try
        {
            using var json = JsonDocument.Parse(run.ResultJson);
            return json.RootElement.ValueKind == JsonValueKind.Object
                   && json.RootElement.TryGetProperty("closed_by", out var value)
                   && value.ValueKind == JsonValueKind.String && value.GetString() == "backend-reaper";
        }
        catch (JsonException) { return false; }
    }

    public static AgentTerminalRecoveryState Evaluate(AgentRun run, AgentAcceptanceSettings settings, DateTimeOffset now)
    {
        if (!IsBackendTimeout(run)) return new(false, null);
        var until = new DateTimeOffset(DateTime.SpecifyKind(run.DeadlineAt, DateTimeKind.Utc))
            .AddSeconds(settings.TerminalRecoveryGraceSeconds);
        return new(now < until, until, now < until ? (int)Math.Ceiling((until - now).TotalSeconds) : 0);
    }

    /// <summary>Wait for a projection admitted just before grace expiry to commit.
    /// After this statement releases its share lock, no new terminal can be
    /// admitted for an expired timeout, so a final timeout response is stable.</summary>
    public static async Task<AgentRun> StabilizeExpiredAsync(DbSet<AgentRun> runs, AgentRun snapshot,
        AgentAcceptanceSettings settings, CancellationToken cancellationToken)
    {
        if (!IsBackendTimeout(snapshot) || Evaluate(snapshot, settings, DateTimeOffset.UtcNow).IsProvisionalTerminal)
            return snapshot;
        return await runs.FromSql($"SELECT * FROM agent_runs WHERE \"Id\" = {snapshot.Id} FOR SHARE")
            .AsNoTracking().SingleAsync(cancellationToken);
    }
}
