using BlogApp.Core.Application.Common.Messaging;
using BlogApp.Core.Application.Features.AgentFeature.Commands.ResumeAgentRunCommand;
using BlogApp.Core.Domain.Entities;
using BlogApp.Core.Domain.Enums;
using BlogApp.Infrastructure.Messaging;
using BlogApp.Infrastructure.Persistence;
using BlogApp.Presentation.Api.Tests.Messaging.Projection;
using Microsoft.EntityFrameworkCore;
using Xunit;

namespace BlogApp.Presentation.Api.Tests.Agent;

/// <summary>
/// W6 F4: projection resume store artık onaylı proposal kaydından checkpoint
/// referansı üretir — referansın HER ZAMAN null olması üretimde resume komutunun
/// asla yazılmaması demekti (mutlu yol yalnız test double'ıyla geçiyordu).
/// Bu testler GERÇEK store'u gerçek Postgres üstünde sabitler:
/// - confirmed|resume_sent proposal → TEK TANIM checkpoint referansı + sürüm.
/// - yalnız 'proposed' → referans YOK (fail-closed korunur; backend uydurmaz).
/// - applied needs_input inbox kaydı → InputVersion.
/// </summary>
[Collection("agent-b10")]
public class ProjectionAgentResumeStateStoreTests : IAsyncLifetime
{
    private readonly AgentB10DatabaseFixture _fixture;

    public ProjectionAgentResumeStateStoreTests(AgentB10DatabaseFixture fixture) => _fixture = fixture;

    public Task InitializeAsync() => _fixture.ResetAsync();

    public Task DisposeAsync() => Task.CompletedTask;

    [Fact]
    public async Task ConfirmedProposal_YieldsCanonicalCheckpointReference_AndVersion()
    {
        var runId = Guid.NewGuid();
        var proposalId = Guid.NewGuid();
        await using var context = _fixture.CreateContext();
        await AgentRunSeeder.SeedAsync(context, runId);
        context.AgentProposals.Add(ConfirmedProposal(runId, proposalId, status: AgentProposalStatus.Confirmed));
        await context.SaveChangesAsync();

        var store = new ProjectionAgentResumeStateStore(context);
        var pending = await store.GetPendingAsync(runId);

        Assert.NotNull(pending);
        Assert.Equal(proposalId.ToString("D"), pending!.ProposalId);
        Assert.Equal(1, pending.ProposalVersion);
        Assert.Equal(
            AgentCollaborationEnvelopeComposer.ComposeCheckpointReference(runId, proposalId),
            pending.CheckpointReference);
    }

    [Fact]
    public async Task ResumeSentProposal_StillYieldsReference_HandlerReplays()
    {
        // resume_sent: komut zaten üretilmiş; store referansı vermeye devam eder,
        // handler outbox varlık kontrolüyle "replay" kararı verir (ikinci mesaj yok).
        var runId = Guid.NewGuid();
        await using var context = _fixture.CreateContext();
        await AgentRunSeeder.SeedAsync(context, runId);
        context.AgentProposals.Add(ConfirmedProposal(runId, Guid.NewGuid(), status: AgentProposalStatus.ResumeSent));
        await context.SaveChangesAsync();

        var pending = await new ProjectionAgentResumeStateStore(context).GetPendingAsync(runId);

        Assert.NotNull(pending);
        Assert.False(string.IsNullOrWhiteSpace(pending!.CheckpointReference));
    }

    [Fact]
    public async Task UnconfirmedProposal_YieldsNoCheckpointReference_FailClosed()
    {
        var runId = Guid.NewGuid();
        await using var context = _fixture.CreateContext();
        await AgentRunSeeder.SeedAsync(context, runId);
        context.AgentProposals.Add(ConfirmedProposal(runId, Guid.NewGuid(), status: AgentProposalStatus.Proposed));
        await context.SaveChangesAsync();

        var pending = await new ProjectionAgentResumeStateStore(context).GetPendingAsync(runId);

        // Onaylanmamış proposal checkpoint kaynağı DEĞİLDİR: referans null kalır;
        // handler fail-closed davranışını korur (komut üretilmez).
        Assert.Null(pending?.CheckpointReference);
    }

    [Fact]
    public async Task AppliedNeedsInputInbox_YieldsInputVersion()
    {
        var runId = Guid.NewGuid();
        await using var context = _fixture.CreateContext();
        await AgentRunSeeder.SeedAsync(context, runId);
        context.AgentEventInboxes.Add(new AgentEventInbox
        {
            ConsumerName = AgentRunEventProjectionHandler.ConsumerName,
            MessageId = Guid.NewGuid(),
            MessageType = AgentMessageTypes.RunNeedsInput,
            RunId = runId,
            EventSequence = 7,
            Status = "applied",
            CreatedAt = DateTime.UtcNow,
        });
        await context.SaveChangesAsync();

        var pending = await new ProjectionAgentResumeStateStore(context).GetPendingAsync(runId);

        Assert.NotNull(pending);
        Assert.Equal(7, pending!.InputVersion);
        Assert.Null(pending.CheckpointReference); // onaylı proposal yok: uydurulmaz
    }

    [Fact]
    public async Task UnknownRun_ReturnsNull()
    {
        await using var context = _fixture.CreateContext();

        var pending = await new ProjectionAgentResumeStateStore(context).GetPendingAsync(Guid.NewGuid());

        Assert.Null(pending);
    }

    private static AgentProposal ConfirmedProposal(Guid runId, Guid proposalId, string status) => new()
    {
        Id = Guid.NewGuid(),
        ProposalId = proposalId,
        Version = 1,
        RunId = runId,
        ArticleId = Guid.NewGuid(),
        ArticleRevision = 3,
        BaseContentHash = new string('a', 64),
        ContentHash = new string('b', 64),
        Summary = "İş birliği önerisi — W6 F4 store testi.",
        OwnerKey = "u:b5-test-user",
        ExpiresAt = DateTimeOffset.UtcNow.AddHours(24),
        Status = status,
        CreatedAt = DateTime.UtcNow,
    };
}
