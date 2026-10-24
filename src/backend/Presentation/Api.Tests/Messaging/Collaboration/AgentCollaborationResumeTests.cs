using BlogApp.Core.Application.Common.Interfaces.Data;
using BlogApp.Core.Application.Common.Messaging;
using BlogApp.Core.Application.Common.Options;
using BlogApp.Core.Application.Features.AgentFeature.Collaboration;
using BlogApp.Core.Domain.Entities;
using BlogApp.Core.Domain.Enums;
using BlogApp.Infrastructure.Messaging;
using BlogApp.Infrastructure.Persistence;
using BlogApp.Infrastructure.Persistence.Repositories;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging.Abstractions;
using Microsoft.Extensions.Options;
using Xunit;

namespace BlogApp.Presentation.Api.Tests.Messaging.Collaboration;

/// <summary>
/// B9 resume durum makinesi (plan B9: "proposed → confirmed → resume_sent";
/// "Aynı onay için ikinci bir resume mesajı üretip graph'ı iki kez devam
/// ettirme") — gerçek Postgres üzerinde: onaysız işlem, hash uyuşmazlığı,
/// sahiplik ve idempotent resume.
/// </summary>
[Collection("agent-b9-collaboration")]
public class AgentCollaborationResumeTests : IAsyncLifetime
{
    private readonly AgentCollaborationDatabaseFixture _fixture;

    public AgentCollaborationResumeTests(AgentCollaborationDatabaseFixture fixture)
    {
        _fixture = fixture;
    }

    public Task InitializeAsync() => _fixture.ResetAsync();

    public Task DisposeAsync() => Task.CompletedTask;

    private static AgentCollaborationService CreateService(AppDbContext context) =>
        new(
            new UnitOfWork(context),
            context,
            new EfAgentCollaborationStore(context),
            new EfOutboxWriter(context),
            Options.Create(new AgentMessagingSettings()),
            NullLogger<AgentCollaborationService>.Instance);

    private async Task<(Guid RunId, Guid ProposalId, string Hash)> SeedConfirmedProposalAsync()
    {
        var runId = Guid.NewGuid();
        await using var context = _fixture.CreateContext();
        context.AgentRuns.Add(new AgentRun
        {
            Id = runId,
            ConversationId = Guid.NewGuid(),
            TurnSequence = 1,
            OwnerKey = "u:b9-owner",
            IdempotencyKey = $"idem-{Guid.NewGuid():N}",
            IdempotencyPayloadHash = new string('a', 64),
            Status = AgentRunStatus.Accepted,
            Question = "B9 resume testi",
            Language = "tr",
            ModePreference = "fast",
            BudgetProfile = "default",
            ContextSnapshotReference = $"agent-run/{runId:D}/turn/1",
            ContextSnapshotJson = """{"question":"B9 resume testi"}""",
            DeadlineAt = DateTime.UtcNow.AddMinutes(10),
            AcceptedAt = DateTime.UtcNow,
        });
        var summary = "İş birliği önerisi — konuk yazı.";
        var proposalId = Guid.NewGuid();
        context.AgentProposals.Add(new AgentProposal
        {
            Id = Guid.NewGuid(),
            ProposalId = proposalId,
            Version = 1,
            RunId = runId,
            ArticleId = Guid.NewGuid(),
            ArticleRevision = 3,
            BaseContentHash = new string('b', 64),
            ContentHash = AgentCollaborationContentHash.Compute(summary),
            Summary = summary,
            OwnerKey = "u:b9-owner",
            ExpiresAt = DateTimeOffset.UtcNow.AddHours(168),
            Status = AgentProposalStatus.Confirmed,
            ConfirmedAt = DateTimeOffset.UtcNow,
            ConfirmedContentHash = AgentCollaborationContentHash.Compute(summary),
        });
        await context.SaveChangesAsync();
        return (runId, proposalId, AgentCollaborationContentHash.Compute(summary));
    }

    [Fact]
    public async Task Resume_AfterConfirmation_WritesContractValidResumeCommand()
    {
        var (runId, proposalId, hash) = await SeedConfirmedProposalAsync();
        await using var context = _fixture.CreateContext();

        var result = await CreateService(context).ResumeRequestAsync(runId, proposalId, hash, "u:b9-owner");

        Assert.True(result.Sent, result.RejectionReason);
        Assert.Equal(AgentProposalStatus.ResumeSent,
            (await context.AgentProposals.AsNoTracking().SingleAsync(p => p.ProposalId == proposalId)).Status);

        var outbox = await context.OutboxMessages.AsNoTracking().SingleAsync(m => m.RunId == runId);
        Assert.Equal(AgentMessageTypes.ResumeRequested, outbox.MessageType);
        Assert.Equal("agent.resume.requested.v1", outbox.RoutingKey);
        var validation = new AgentContractValidator(new AgentMessagingSettings()).Validate(outbox.EnvelopeJson);
        Assert.True(validation.IsValid);
        Assert.Equal($"agent-collab/{runId:D}/proposal/{proposalId:D}",
            (string?)validation.PayloadNode!["checkpoint_reference"]);
        Assert.Equal("u:b9-owner", (string?)validation.PayloadNode!["user_ref"]);
    }

    [Fact]
    public async Task Resume_SecondCallForSameConfirmation_IsDuplicate_WritesNoSecondMessage()
    {
        var (runId, proposalId, hash) = await SeedConfirmedProposalAsync();
        await using var first = _fixture.CreateContext();
        await using var second = _fixture.CreateContext();
        var service = CreateService(first);
        var again = CreateService(second);

        var firstResult = await service.ResumeRequestAsync(runId, proposalId, hash, "u:b9-owner");
        var secondResult = await again.ResumeRequestAsync(runId, proposalId, hash, "u:b9-owner");

        Assert.True(firstResult.Sent);
        Assert.True(secondResult.Duplicate); // aynı onay için ikinci resume ÜRETİLMEZ

        await using var verify = _fixture.CreateContext();
        Assert.Equal(1, await verify.OutboxMessages.AsNoTracking().CountAsync(m => m.RunId == runId));
    }

    [Fact]
    public async Task Resume_ConcurrentCalls_ProduceExactlyOneResumeMessage()
    {
        var (runId, proposalId, hash) = await SeedConfirmedProposalAsync();

        var firstTask = Task.Run(async () =>
        {
            await using var context = _fixture.CreateContext();
            return await CreateService(context).ResumeRequestAsync(runId, proposalId, hash, "u:b9-owner");
        });
        var secondTask = Task.Run(async () =>
        {
            await using var context = _fixture.CreateContext();
            return await CreateService(context).ResumeRequestAsync(runId, proposalId, hash, "u:b9-owner");
        });
        var results = await Task.WhenAll(firstTask, secondTask);

        Assert.Equal(1, results.Count(r => r.Sent));
        Assert.Equal(1, results.Count(r => r.Duplicate));

        await using var verify = _fixture.CreateContext();
        Assert.Equal(1, await verify.OutboxMessages.AsNoTracking().CountAsync(m => m.RunId == runId));
    }

    [Fact]
    public async Task Resume_WithoutConfirmation_IsRejected_WritesNoMessage()
    {
        // Onaysız işlem: öneri yalnız upsert edilmiş (proposed); resume üretilmez.
        var runId = Guid.NewGuid();
        await using var context = _fixture.CreateContext();
        context.AgentRuns.Add(new AgentRun
        {
            Id = runId,
            ConversationId = Guid.NewGuid(),
            TurnSequence = 1,
            OwnerKey = "u:b9-owner",
            IdempotencyKey = $"idem-{Guid.NewGuid():N}",
            IdempotencyPayloadHash = new string('a', 64),
            Status = AgentRunStatus.Accepted,
            Question = "B9 onaysız testi",
            Language = "tr",
            ModePreference = "fast",
            BudgetProfile = "default",
            ContextSnapshotReference = $"agent-run/{runId:D}/turn/1",
            ContextSnapshotJson = """{"question":"B9 onaysız testi"}""",
            DeadlineAt = DateTime.UtcNow.AddMinutes(10),
            AcceptedAt = DateTime.UtcNow,
        });
        var summary = "İş birliği önerisi — konuk yazı.";
        var proposalId = Guid.NewGuid();
        context.AgentProposals.Add(new AgentProposal
        {
            Id = Guid.NewGuid(),
            ProposalId = proposalId,
            Version = 1,
            RunId = runId,
            ArticleId = Guid.NewGuid(),
            ArticleRevision = 3,
            BaseContentHash = new string('b', 64),
            ContentHash = AgentCollaborationContentHash.Compute(summary),
            Summary = summary,
            OwnerKey = "u:b9-owner",
            ExpiresAt = DateTimeOffset.UtcNow.AddHours(168),
            Status = AgentProposalStatus.Proposed,
        });
        await context.SaveChangesAsync();

        var result = await CreateService(context).ResumeRequestAsync(runId, proposalId,
            AgentCollaborationContentHash.Compute(summary), "u:b9-owner");

        Assert.Equal(CollaborateResumeOutcome.RejectedVersion, result.Outcome);
        Assert.Contains("onaylanmadı", result.RejectionReason);
        Assert.False(await context.OutboxMessages.AsNoTracking().AnyAsync(m => m.RunId == runId));
    }

    [Theory]
    [InlineData(AgentRunStatus.Cancelled)]
    [InlineData(AgentRunStatus.Failed)]
    [InlineData(AgentRunStatus.Completed)]
    public async Task Resume_TerminalRunDoesNotTransitionProposalOrWriteOutbox(AgentRunStatus status)
    {
        var (runId, proposalId, hash) = await SeedConfirmedProposalAsync();
        await using var context = _fixture.CreateContext();
        await context.AgentRuns.Where(r => r.Id == runId).ExecuteUpdateAsync(update => update.SetProperty(r => r.Status, status));
        var result = await CreateService(context).ResumeRequestAsync(runId, proposalId, hash, "u:b9-owner");
        Assert.Equal(CollaborateResumeOutcome.RejectedVersion, result.Outcome);
        Assert.False(await context.OutboxMessages.AnyAsync(m => m.RunId == runId));
        Assert.Equal(AgentProposalStatus.Confirmed, (await context.AgentProposals.SingleAsync(p => p.ProposalId == proposalId)).Status);
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task Resume_ExpiredProposalOrRunDeadlineIsRejected(bool expiredRun)
    {
        var (runId, proposalId, hash) = await SeedConfirmedProposalAsync();
        await using var context = _fixture.CreateContext();
        if (expiredRun)
            await context.AgentRuns.Where(r => r.Id == runId).ExecuteUpdateAsync(update => update.SetProperty(r => r.DeadlineAt, DateTime.UtcNow.AddSeconds(-1)));
        else
            await context.AgentProposals.Where(p => p.ProposalId == proposalId).ExecuteUpdateAsync(update => update.SetProperty(p => p.ExpiresAt, DateTimeOffset.UtcNow.AddSeconds(-1)));
        var result = await CreateService(context).ResumeRequestAsync(runId, proposalId, hash, "u:b9-owner");
        Assert.Equal(CollaborateResumeOutcome.RejectedVersion, result.Outcome);
        Assert.False(await context.OutboxMessages.AnyAsync(m => m.RunId == runId));
    }

    [Fact]
    public async Task Resume_WithTamperedHash_IsRejected()
    {
        var (runId, proposalId, _) = await SeedConfirmedProposalAsync();
        await using var context = _fixture.CreateContext();

        var result = await CreateService(context).ResumeRequestAsync(
            runId, proposalId, AgentCollaborationContentHash.Compute("değiştirilmiş sürüm"), "u:b9-owner");

        Assert.Equal(CollaborateResumeOutcome.RejectedVersion, result.Outcome);
        Assert.False(await context.OutboxMessages.AsNoTracking().AnyAsync(m => m.RunId == runId));
    }

    [Fact]
    public async Task Resume_ForeignOwner_IsRejectedOwner_WritesNoMessage()
    {
        var (runId, proposalId, hash) = await SeedConfirmedProposalAsync();
        await using var context = _fixture.CreateContext();

        var result = await CreateService(context).ResumeRequestAsync(runId, proposalId, hash, "u:another-user");

        Assert.Equal(CollaborateResumeOutcome.RejectedOwner, result.Outcome);
        Assert.False(await context.OutboxMessages.AsNoTracking().AnyAsync(m => m.RunId == runId));
        Assert.Equal(AgentProposalStatus.Confirmed,
            (await context.AgentProposals.AsNoTracking().SingleAsync(p => p.ProposalId == proposalId)).Status);
    }

    [Fact]
    public async Task Resume_UnknownProposal_IsRejected()
    {
        var (runId, _, hash) = await SeedConfirmedProposalAsync();
        await using var context = _fixture.CreateContext();

        var result = await CreateService(context).ResumeRequestAsync(runId, Guid.NewGuid(), hash, "u:b9-owner");

        Assert.Equal(CollaborateResumeOutcome.RejectedVersion, result.Outcome);
    }
}
