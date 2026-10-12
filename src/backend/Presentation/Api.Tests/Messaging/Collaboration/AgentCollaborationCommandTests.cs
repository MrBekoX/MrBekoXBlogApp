using BlogApp.Core.Application.Common.Errors;
using BlogApp.Core.Application.Common.Interfaces.Data;
using BlogApp.Core.Application.Common.Interfaces.Messaging;
using BlogApp.Core.Application.Common.Interfaces.Persistence;
using BlogApp.Core.Application.Common.Interfaces.Services;
using BlogApp.Core.Application.Common.Models;
using BlogApp.Core.Application.Common.Messaging;
using BlogApp.Core.Application.Common.Options;
using BlogApp.Core.Application.Features.AgentFeature.Collaboration;
using BlogApp.Core.Application.Features.AgentFeature.Commands.RequestCollaborationResumeCommand;
using BlogApp.Core.Application.Features.AgentFeature.Commands.SubmitCollaborationConfirmationCommand;
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
/// Açık backend eylem testleri (plan B9: "Gönderim onayını açık backend eylemiyle al;
/// LLM metnindeki onay ifadesini yetkilendirme kaynağı yapma"). Onayın TEK girişi
/// komuttur: oturumsuz çağrı Unauthorized; komut sahipliği oturumdan çözümler —
/// istemcinin owner iddiası yoktur.
/// </summary>
[Collection("agent-b9-collaboration")]
public class AgentCollaborationCommandTests : IAsyncLifetime
{
    private readonly AgentCollaborationDatabaseFixture _fixture;

    public AgentCollaborationCommandTests(AgentCollaborationDatabaseFixture fixture)
    {
        _fixture = fixture;
    }

    public Task InitializeAsync() => _fixture.ResetAsync();

    public Task DisposeAsync() => Task.CompletedTask;

    private SubmitCollaborationConfirmationHandler CreateSubmitHandler(Guid? userId) =>
        new(
            new TestCurrentUser(userId),
            CreateCollaborationService());

    private RequestCollaborationResumeHandler CreateResumeHandler(Guid? userId) =>
        new(
            new TestCurrentUser(userId),
            CreateCollaborationService());

    private AgentCollaborationService CreateCollaborationService()
    {
        var context = _fixture.CreateContext();
        return new AgentCollaborationService(
            new UnitOfWork(context),
            context,
            new EfAgentCollaborationStore(context),
            new EfOutboxWriter(context),
            Options.Create(new AgentMessagingSettings()),
            NullLogger<AgentCollaborationService>.Instance);
    }

    [Fact]
    public async Task Submit_WithoutAnyIdentity_IsUnauthorized()
    {
        var handler = CreateSubmitHandler(userId: null);

        var result = await handler.Handle(new SubmitCollaborationConfirmationRequest
        {
            RunId = Guid.NewGuid(),
            ProposalId = Guid.NewGuid(),
            SubmittedContentHash = new string('a', 64),
        }, CancellationToken.None);

        Assert.True(result.IsFailure);
        Assert.Equal(ErrorCategory.Unauthorized, result.ErrorDetail!.Category);
    }

    [Fact]
    public async Task Resume_WithoutAnyIdentity_IsUnauthorized()
    {
        var handler = CreateResumeHandler(userId: null);

        var result = await handler.Handle(new RequestCollaborationResumeRequest
        {
            RunId = Guid.NewGuid(),
            ProposalId = Guid.NewGuid(),
            ExpectedContentHash = new string('a', 64),
        }, CancellationToken.None);

        Assert.True(result.IsFailure);
        Assert.Equal(ErrorCategory.Unauthorized, result.ErrorDetail!.Category);
    }

    [Fact]
    public async Task Submit_WithUserIdentity_ResolvesOwnerFromSession_AndConfirms()
    {
        var userId = Guid.NewGuid();
        var ownerKey = $"u:{userId:D}";
        var runId = Guid.NewGuid();
        await using (var seed = _fixture.CreateContext())
        {
            seed.AgentRuns.Add(new AgentRun
            {
                Id = runId,
                ConversationId = Guid.NewGuid(),
                TurnSequence = 1,
                OwnerKey = ownerKey,
                IdempotencyKey = $"idem-{Guid.NewGuid():N}",
                IdempotencyPayloadHash = new string('a', 64),
                Status = AgentRunStatus.Accepted,
                Question = "B9 komut testi",
                Language = "tr",
                ModePreference = "fast",
                BudgetProfile = "default",
                ContextSnapshotReference = $"agent-run/{runId:D}/turn/1",
                ContextSnapshotJson = """{"question":"B9 komut testi"}""",
                DeadlineAt = DateTime.UtcNow.AddMinutes(10),
                AcceptedAt = DateTime.UtcNow,
            });
            var summary = "İş birliği önerisi — komut onayı.";
            seed.AgentProposals.Add(new AgentProposal
            {
                Id = Guid.NewGuid(),
                ProposalId = Guid.NewGuid(),
                Version = 1,
                RunId = runId,
                ArticleId = Guid.NewGuid(),
                ArticleRevision = 3,
                BaseContentHash = new string('b', 64),
                ContentHash = AgentCollaborationContentHash.Compute(summary),
                Summary = summary,
                OwnerKey = ownerKey,
                ExpiresAt = DateTimeOffset.UtcNow.AddHours(168),
                Status = AgentProposalStatus.Proposed,
            });
            await seed.SaveChangesAsync();
        }

        // Komut taşır TAM OLARAK: run + proposal + hash (+ misafir oturumu);
        // owner alanı YOKTUR — sahiplik oturumdan çözülür.
        var proposalId = (await _fixture.CreateContext().AgentProposals
            .AsNoTracking().SingleAsync(p => p.RunId == runId)).ProposalId;
        var hash = AgentCollaborationContentHash.Compute("İş birliği önerisi — komut onayı.");

        var result = await CreateSubmitHandler(userId).Handle(new SubmitCollaborationConfirmationRequest
        {
            RunId = runId,
            ProposalId = proposalId,
            SubmittedContentHash = hash,
        }, CancellationToken.None);

        Assert.True(result.IsSuccess, result.ErrorDetail?.Message);
        Assert.True(result.Value!.Accepted);

        // Onay kaydı + gerçek backend sonucu aynı transaction'da.
        await using var verify = _fixture.CreateContext();
        Assert.Equal(AgentProposalStatus.Confirmed,
            (await verify.AgentProposals.AsNoTracking().SingleAsync(p => p.ProposalId == proposalId)).Status);
        Assert.True(await verify.OutboxMessages.AsNoTracking()
            .AnyAsync(m => m.RunId == runId && m.MessageType == AgentMessageTypes.ActionResult));
    }

    [Fact]
    public async Task Submit_ForeignRunViaSession_IsForbidden()
    {
        var runId = Guid.NewGuid();
        await using (var seed = _fixture.CreateContext())
        {
            seed.AgentRuns.Add(new AgentRun
            {
                Id = runId,
                ConversationId = Guid.NewGuid(),
                TurnSequence = 1,
                OwnerKey = "u:other-user",
                IdempotencyKey = $"idem-{Guid.NewGuid():N}",
                IdempotencyPayloadHash = new string('a', 64),
                Status = AgentRunStatus.Accepted,
                Question = "B9 yabancı oturum testi",
                Language = "tr",
                ModePreference = "fast",
                BudgetProfile = "default",
                ContextSnapshotReference = $"agent-run/{runId:D}/turn/1",
                ContextSnapshotJson = """{"question":"B9 yabancı oturum testi"}""",
                DeadlineAt = DateTime.UtcNow.AddMinutes(10),
                AcceptedAt = DateTime.UtcNow,
            });
            await seed.SaveChangesAsync();
        }

        var result = await CreateSubmitHandler(Guid.NewGuid()).Handle(new SubmitCollaborationConfirmationRequest
        {
            RunId = runId,
            ProposalId = Guid.NewGuid(),
            SubmittedContentHash = new string('a', 64),
        }, CancellationToken.None);

        Assert.True(result.IsFailure);
        Assert.Equal(ErrorCategory.Forbidden, result.ErrorDetail!.Category);
        await using var verify = _fixture.CreateContext();
        Assert.False(await verify.OutboxMessages.AsNoTracking().AnyAsync(m => m.RunId == runId));
    }

    private sealed class TestCurrentUser(Guid? userId) : ICurrentUserService
    {
        public Guid? UserId => userId;
        public string? UserName => null;
        public string? Email => null;
        public string? CorrelationId => null;
        public bool IsAuthenticated => userId is not null;
        public bool IsInRole(string role) => false;
    }
}
