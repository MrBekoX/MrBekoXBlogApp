using BlogApp.Core.Application.Common.Messaging;
using BlogApp.Core.Domain.Enums;
using Xunit;

namespace BlogApp.Presentation.Api.Tests.Messaging.Projection;

/// <summary>
/// B5 terminal-öncelik ve sıra kurallarının saf çekirdek testleri (broker'sız):
/// duplicate yoksayılır, sıra gerilemesi uygulanmaz, terminal sonrası eski
/// non-terminal olay terminal durumu geriye götürmez, daha yeni terminal uygulanır.
/// </summary>
public class AgentRunProjectionRuleTests
{
    [Fact]
    public void Duplicate_delivery_is_never_reapplied()
    {
        var decision = AgentRunEventProjectionRules.Decide(
            duplicateDelivery: true,
            runIsTerminal: false,
            lastAppliedSequence: 4,
            incomingSequence: 7,
            incomingIsTerminal: false);
        Assert.Equal(AgentEventDecision.Duplicate, decision);
    }

    [Fact]
    public void Sequence_regression_is_stale()
    {
        var decision = AgentRunEventProjectionRules.Decide(
            duplicateDelivery: false,
            runIsTerminal: false,
            lastAppliedSequence: 5,
            incomingSequence: 4,
            incomingIsTerminal: false);
        Assert.Equal(AgentEventDecision.Stale, decision);
    }

    [Fact]
    public void Equal_sequence_is_stale()
    {
        var decision = AgentRunEventProjectionRules.Decide(
            duplicateDelivery: false,
            runIsTerminal: false,
            lastAppliedSequence: 5,
            incomingSequence: 5,
            incomingIsTerminal: false);
        Assert.Equal(AgentEventDecision.Stale, decision);
    }

    [Fact]
    public void Old_progress_after_terminal_cannot_regress_status()
    {
        // Terminal sonrası "eski" progress: sequence düşük veya yüksek olsa da
        // non-terminal olay terminal run'a uygulanmaz (terminal-öncelik kuralı).
        var lowerSequence = AgentRunEventProjectionRules.Decide(
            duplicateDelivery: false,
            runIsTerminal: true,
            lastAppliedSequence: 9,
            incomingSequence: 8,
            incomingIsTerminal: false);
        Assert.Equal(AgentEventDecision.Stale, lowerSequence);

        var higherSequence = AgentRunEventProjectionRules.Decide(
            duplicateDelivery: false,
            runIsTerminal: true,
            lastAppliedSequence: 9,
            incomingSequence: 10,
            incomingIsTerminal: false);
        Assert.Equal(AgentEventDecision.Stale, higherSequence);
    }

    [Fact]
    public void Newer_terminal_event_over_conflicting_terminal_is_applied()
    {
        var decision = AgentRunEventProjectionRules.Decide(
            duplicateDelivery: false,
            runIsTerminal: true,
            lastAppliedSequence: 9,
            incomingSequence: 10,
            incomingIsTerminal: true);
        Assert.Equal(AgentEventDecision.Apply, decision);
    }

    [Fact]
    public void Fresh_non_terminal_event_on_active_run_is_applied()
    {
        var decision = AgentRunEventProjectionRules.Decide(
            duplicateDelivery: false,
            runIsTerminal: false,
            lastAppliedSequence: 2,
            incomingSequence: 3,
            incomingIsTerminal: false);
        Assert.Equal(AgentEventDecision.Apply, decision);
    }

    [Fact]
    public void Terminal_statuses_match_plan_set()
    {
        Assert.Equal(
            [AgentRunStatus.Completed, AgentRunStatus.PartiallyCompleted, AgentRunStatus.Failed, AgentRunStatus.Cancelled],
            AgentRunStatusRules.TerminalStatuses);
        Assert.False(AgentRunStatus.Accepted.IsTerminal());
        Assert.True(AgentRunStatus.Completed.IsTerminal());
    }
}
