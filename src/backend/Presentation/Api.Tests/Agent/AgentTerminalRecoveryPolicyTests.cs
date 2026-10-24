using BlogApp.Core.Application.Common.Options;
using BlogApp.Core.Application.Features.AgentFeature.Services;
using BlogApp.Core.Domain.Entities;
using BlogApp.Core.Domain.Enums;
using Xunit;

namespace BlogApp.Presentation.Api.Tests.Agent;

public sealed class AgentTerminalRecoveryPolicyTests
{
    [Fact]
    public void Timeout_IsProvisionalOnlyBeforeTheExactServerDeadlinePlusGrace()
    {
        var deadline = new DateTimeOffset(2026, 10, 24, 12, 0, 0, TimeSpan.Zero);
        var run = new AgentRun { Status = AgentRunStatus.Failed, DeadlineAt = deadline.UtcDateTime,
            ResultJson = AgentRunDeadlineReaper.AgentDeadlineResultJson };
        var settings = new AgentAcceptanceSettings { TerminalRecoveryGraceSeconds = 300 };
        var before = AgentTerminalRecoveryPolicy.Evaluate(run, settings, deadline.AddSeconds(299.999));
        Assert.True(before.IsProvisionalTerminal);
        Assert.Equal(deadline.AddSeconds(300), before.ReconciliationUntil);
        Assert.False(AgentTerminalRecoveryPolicy.Evaluate(run, settings, deadline.AddSeconds(300)).IsProvisionalTerminal);
        settings.TerminalRecoveryGraceSeconds = 0;
        Assert.False(AgentTerminalRecoveryPolicy.Evaluate(run, settings, deadline).IsProvisionalTerminal);
    }

    [Theory]
    [InlineData(AgentRunStatus.Completed)]
    [InlineData(AgentRunStatus.Cancelled)]
    [InlineData(AgentRunStatus.Accepted)]
    public void ActualWorkerStatesNeverBecomeProvisional(AgentRunStatus status)
    {
        var run = new AgentRun { Status = status, DeadlineAt = DateTime.UtcNow,
            ResultJson = AgentRunDeadlineReaper.AgentDeadlineResultJson };
        Assert.Equal(new AgentTerminalRecoveryState(false, null),
            AgentTerminalRecoveryPolicy.Evaluate(run, new(), DateTimeOffset.UtcNow));
    }

    [Theory]
    [InlineData("{bad")]
    [InlineData("[]")]
    [InlineData("{\"closed_by\":null}")]
    [InlineData("{\"closed_by\":\"worker\"}")]
    public void InvalidOrWorkerFailureMarkersAreFinal(string json)
    {
        var run = new AgentRun { Status = AgentRunStatus.Failed, ResultJson = json };
        Assert.False(AgentTerminalRecoveryPolicy.IsBackendTimeout(run));
    }
}
