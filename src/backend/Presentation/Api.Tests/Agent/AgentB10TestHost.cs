using BlogApp.Core.Application.Common.Interfaces.Data;
using BlogApp.Core.Application.Common.Interfaces.Persistence;
using BlogApp.Core.Application.Common.Interfaces.Services;
using BlogApp.Core.Domain.Entities;
using BlogApp.Core.Domain.Enums;
using BlogApp.Infrastructure.Persistence;
using BlogApp.Infrastructure.Persistence.Repositories;

namespace BlogApp.Presentation.Api.Tests.Agent;

/// <summary>B10 test yardımcıları: kimlik test çifti, run/inbox seed.</summary>
internal static class AgentB10TestHost
{
    public static UnitOfWork NewUnitOfWork(AppDbContext context) => new(context);

    public static async Task<AgentRun> SeedRunAsync(
        AppDbContext context,
        Guid? runId = null,
        string ownerKey = "u:b10-user",
        AgentRunStatus status = AgentRunStatus.Accepted,
        Guid? articleId = null,
        string? resultJson = null,
        string modePreference = "auto",
        string? selectedMode = null,
        DateTime? terminalAt = null)
    {
        var run = new AgentRun
        {
            Id = runId ?? Guid.NewGuid(),
            ConversationId = Guid.NewGuid(),
            TurnSequence = 1,
            OwnerKey = ownerKey,
            IdempotencyKey = $"idem-{Guid.NewGuid():N}",
            IdempotencyPayloadHash = new string('a', 64),
            Status = status,
            Question = "B10 test sorusu",
            Language = "tr",
            ModePreference = modePreference,
            BudgetProfile = "standard",
            SelectedMode = selectedMode,
            ArticleId = articleId,
            ContextSnapshotReference = $"agent-run/{runId}/turn/1",
            ContextSnapshotJson = """{"question":"B10 test sorusu"}""",
            DeadlineAt = DateTime.UtcNow.AddMinutes(10),
            AcceptedAt = DateTime.UtcNow.AddMinutes(-2),
            ResultJson = resultJson,
            TerminalAt = terminalAt,
        };
        context.AgentRuns.Add(run);
        await context.SaveChangesAsync();
        return run;
    }

    /// <summary>Projection inbox kaydı: applied needs_input olayı (B10 resume sürüm doğrulamasının kaynağı).</summary>
    public static async Task SeedAppliedNeedsInputAsync(AppDbContext context, Guid runId, long eventSequence)
    {
        context.AgentEventInboxes.Add(new AgentEventInbox
        {
            ConsumerName = "backend-agent-events",
            MessageId = Guid.NewGuid(),
            MessageType = "agent.run.needs_input",
            RunId = runId,
            EventSequence = eventSequence,
            Status = "applied",
            CreatedAt = DateTime.UtcNow,
        });
        await context.SaveChangesAsync();
    }

    public static async Task SeedAppliedEventAsync(
        AppDbContext context,
        Guid runId,
        long eventSequence,
        string messageType,
        string? payloadJson = null,
        string? progressMessage = null)
    {
        context.AgentEventInboxes.Add(new AgentEventInbox
        {
            ConsumerName = "backend-agent-events",
            MessageId = Guid.NewGuid(),
            MessageType = messageType,
            RunId = runId,
            EventSequence = eventSequence,
            Status = "applied",
            // Agent live-steps replay türetme girdisi (ADDITIVE; projection
            // handler'ın applied kayda yazdığı sütunların test karşılığı).
            PayloadJson = payloadJson,
            ProgressMessage = progressMessage,
            CreatedAt = DateTime.UtcNow,
        });
        await context.SaveChangesAsync();
    }
}

/// <summary>Kimlik test çifti (B7 deseni).</summary>
internal sealed class TestCurrentUser(Guid? userId) : ICurrentUserService
{
    public Guid? UserId => userId;

    public string? UserName => userId is null ? null : "b10-test-user";

    public string? Email => null;

    public string? CorrelationId => $"test-{Guid.NewGuid():N}";

    public bool IsAuthenticated => userId is not null;

    public bool IsInRole(string role) => false;
}
