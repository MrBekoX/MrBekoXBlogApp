namespace BlogApp.Core.Application.Common.Options;

/// <summary>Durable startup snapshot settings; disabled unless explicitly configured.</summary>
public sealed class AgentContentSyncSettings
{
    public const string SectionName = "AgentContentSync";

    /// <summary>Maximum article references in one outbox message.</summary>
    public int BatchSize { get; set; } = 50;

    /// <summary>Require the initial durable snapshot before the HTTP server starts.</summary>
    public bool Enabled { get; set; }

    /// <summary>Bounded retries for transient database failures during startup.</summary>
    public int StartupMaxAttempts { get; set; } = 3;

    public int StartupRetryDelaySeconds { get; set; } = 2;
}
