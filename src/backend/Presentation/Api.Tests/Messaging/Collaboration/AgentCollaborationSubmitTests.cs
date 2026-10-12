using System.Data;
using BlogApp.Core.Application.Common.Interfaces.Data;
using BlogApp.Core.Application.Common.Interfaces.Messaging;
using BlogApp.Core.Application.Common.Interfaces.Persistence;
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
/// B9 onay senaryoları (plan B9 kabul ölçütleri) — gerçek Postgres üzerinde:
/// çift tıklama, ağ sonrası tekrar, değiştirilmiş proposal, geçersiz sahiplik,
/// backend kayıt hatası ve "LLM metni onay kaynağı değildir" kanıtı.
/// </summary>
[Collection("agent-b9-collaboration")]
public class AgentCollaborationSubmitTests : IAsyncLifetime
{
    private readonly AgentCollaborationDatabaseFixture _fixture;

    public AgentCollaborationSubmitTests(AgentCollaborationDatabaseFixture fixture)
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

    private async Task<Guid> SeedRunAsync(string ownerKey = "u:b9-owner")
    {
        await using var context = _fixture.CreateContext();
        var run = new AgentRun
        {
            Id = Guid.NewGuid(),
            ConversationId = Guid.NewGuid(),
            TurnSequence = 1,
            OwnerKey = ownerKey,
            IdempotencyKey = $"idem-{Guid.NewGuid():N}",
            IdempotencyPayloadHash = new string('a', 64),
            Status = AgentRunStatus.Accepted, // needs_input terminal değildir; run Accepted kalır (B5)
            Question = "B9 iş birliği testi",
            Language = "tr",
            ModePreference = "fast",
            BudgetProfile = "default",
            ContextSnapshotReference = $"agent-run/{Guid.NewGuid():D}/turn/1",
            ContextSnapshotJson = """{"question":"B9 iş birliği testi"}""",
            DeadlineAt = DateTime.UtcNow.AddMinutes(10),
            AcceptedAt = DateTime.UtcNow,
        };
        context.AgentRuns.Add(run);
        await context.SaveChangesAsync();
        return run.Id;
    }

    private async Task<Guid> SeedProposalAsync(Guid runId, string ownerKey = "u:b9-owner", string summary = "İş birliği önerisi — konuk yazı.")
    {
        await using var context = _fixture.CreateContext();
        var proposal = new AgentProposal
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
        };
        context.AgentProposals.Add(proposal);
        await context.SaveChangesAsync();
        return proposal.ProposalId;
    }

    // ------------------------------------------------------------- onay temel

    [Fact]
    public async Task Submit_WithCurrentHash_IsAccepted_WritesSingleResultMessage()
    {
        var runId = await SeedRunAsync();
        var proposalId = await SeedProposalAsync(runId);
        await using var context = _fixture.CreateContext();
        var service = CreateService(context);
        var hash = AgentCollaborationContentHash.Compute("İş birliği önerisi — konuk yazı.");

        var result = await service.SubmitConfirmationAsync(runId, proposalId, hash, null, "u:b9-owner", DateTimeOffset.UtcNow);

        Assert.True(result.Accepted, result.RejectionReason);
        Assert.Equal(1, result.Version);

        var stored = await context.AgentProposals.AsNoTracking().SingleAsync(p => p.ProposalId == proposalId);
        Assert.Equal(AgentProposalStatus.Confirmed, stored.Status);
        Assert.Equal(hash, stored.ConfirmedContentHash);

        // Gerçek backend sonucu agent'a: accepted + zorunlu applied_article_revision.
        var outbox = await context.OutboxMessages.AsNoTracking().SingleAsync(m => m.RunId == runId);
        Assert.Equal(AgentMessageTypes.ActionResult, outbox.MessageType);
        Assert.Equal("agent.action.result.v1", outbox.RoutingKey);
        var validation = new AgentContractValidator(new AgentMessagingSettings()).Validate(outbox.EnvelopeJson);
        Assert.True(validation.IsValid);
        var payload = validation.PayloadNode!;
        Assert.Equal("accepted", (string?)payload["outcome"]);
        Assert.Equal(proposalId.ToString("D"), (string?)payload["proposal_id"]);
        Assert.Equal(3, (int?)payload["applied_article_revision"]);
    }

    // ------------------------------------------------------------- çift tıklama + ağ tekrarı

    [Fact]
    public async Task Submit_DoubleClick_SecondCallIsDuplicate_WithoutSecondRecordOrMessage()
    {
        var runId = await SeedRunAsync();
        var proposalId = await SeedProposalAsync(runId);
        var hash = AgentCollaborationContentHash.Compute("İş birliği önerisi — konuk yazı.");

        await using var firstContext = _fixture.CreateContext();
        await using var secondContext = _fixture.CreateContext();
        var first = await CreateService(firstContext)
            .SubmitConfirmationAsync(runId, proposalId, hash, null, "u:b9-owner", DateTimeOffset.UtcNow);
        var second = await CreateService(secondContext)
            .SubmitConfirmationAsync(runId, proposalId, hash, null, "u:b9-owner", DateTimeOffset.UtcNow.AddSeconds(1));

        Assert.True(first.Accepted);
        Assert.True(second.Duplicate);

        await using var verify = _fixture.CreateContext();
        Assert.Equal(1, await verify.AgentProposals.AsNoTracking().CountAsync(p => p.ProposalId == proposalId));
        Assert.Equal(1, await verify.OutboxMessages.AsNoTracking().CountAsync(m => m.RunId == runId));
        Assert.Equal(AgentProposalStatus.Confirmed,
            (await verify.AgentProposals.AsNoTracking().SingleAsync(p => p.ProposalId == proposalId)).Status);
    }

    [Fact]
    public async Task Submit_ConcurrentRaces_ProduceExactlyOneAcceptedRecord()
    {
        var runId = await SeedRunAsync();
        var proposalId = await SeedProposalAsync(runId);
        var hash = AgentCollaborationContentHash.Compute("İş birliği önerisi — konuk yazı.");

        // Dağıtık yarış: ayrı context/service'lerle eşzamanlı çift onay.
        var firstTask = Task.Run(async () =>
        {
            await using var context = _fixture.CreateContext();
            return await CreateService(context)
                .SubmitConfirmationAsync(runId, proposalId, hash, null, "u:b9-owner", DateTimeOffset.UtcNow);
        });
        var secondTask = Task.Run(async () =>
        {
            await using var context = _fixture.CreateContext();
            return await CreateService(context)
                .SubmitConfirmationAsync(runId, proposalId, hash, null, "u:b9-owner", DateTimeOffset.UtcNow);
        });
        var results = await Task.WhenAll(firstTask, secondTask);

        Assert.Equal(1, results.Count(r => r.Accepted));
        Assert.Equal(1, results.Count(r => r.Duplicate));

        await using var verify = _fixture.CreateContext();
        Assert.Equal(1, await verify.OutboxMessages.AsNoTracking().CountAsync(m => m.RunId == runId));
        Assert.Equal(AgentProposalStatus.Confirmed,
            (await verify.AgentProposals.AsNoTracking().SingleAsync(p => p.ProposalId == proposalId)).Status);
    }

    // ------------------------------------------------------------- düzenleme (yeni sürüm)

    [Fact]
    public async Task Submit_WithEditedSummary_ConfirmsNewVersion()
    {
        var runId = await SeedRunAsync();
        var proposalId = await SeedProposalAsync(runId);
        await using var context = _fixture.CreateContext();
        var service = CreateService(context);
        var edited = "Düzenlenmiş öneri — aylık konuk yazı.";
        var editedHash = AgentCollaborationContentHash.Compute(edited);

        var result = await service.SubmitConfirmationAsync(runId, proposalId, editedHash, edited, "u:b9-owner", DateTimeOffset.UtcNow);

        Assert.True(result.Accepted, result.RejectionReason);
        Assert.Equal(2, result.Version); // düzenleme YENİ sürüm üretir

        await using var verify = _fixture.CreateContext();
        var versions = await verify.AgentProposals.AsNoTracking()
            .Where(p => p.ProposalId == proposalId).OrderBy(p => p.Version).ToListAsync();
        Assert.Equal(2, versions.Count);
        Assert.Equal(edited, versions[1].Summary);
        Assert.Equal(AgentProposalStatus.Confirmed, versions[1].Status);
        Assert.Equal(editedHash, versions[1].ConfirmedContentHash);
    }

    // ------------------------------------------------------------- değiştirilmiş proposal

    [Fact]
    public async Task Submit_TamperedHash_IsRejectedVersion_AndReportsRejectionToAgent()
    {
        var runId = await SeedRunAsync();
        var proposalId = await SeedProposalAsync(runId);
        await using var context = _fixture.CreateContext();
        var service = CreateService(context);
        var tamperedHash = AgentCollaborationContentHash.Compute("saldırganın değiştirdiği metin");

        var result = await service.SubmitConfirmationAsync(runId, proposalId, tamperedHash, null, "u:b9-owner", DateTimeOffset.UtcNow);

        Assert.True(result.Accepted is false && result.Duplicate is false);
        Assert.Equal(CollaborateSubmitOutcome.RejectedVersion, result.Outcome);

        // Ret kararı gerekçesiyle agent'a TEK KEZ bildirilir (deterministik message_id).
        await using var verify = _fixture.CreateContext();
        var outbox = await verify.OutboxMessages.AsNoTracking().SingleAsync(m => m.RunId == runId);
        var validation = new AgentContractValidator(new AgentMessagingSettings()).Validate(outbox.EnvelopeJson);
        Assert.True(validation.IsValid);
        Assert.Equal("rejected", (string?)validation.PayloadNode!["outcome"]);
        Assert.Contains("sürüm", (string?)validation.PayloadNode!["reason"]);

        // Proposal onaylanmadı; tekrarlı aynı geçersiz gönderim ikinci mesaj üretmez.
        Assert.Equal(AgentProposalStatus.Proposed,
            (await verify.AgentProposals.AsNoTracking().SingleAsync(p => p.ProposalId == proposalId)).Status);
        await using var again = _fixture.CreateContext();
        await CreateService(again).SubmitConfirmationAsync(runId, proposalId, tamperedHash, null, "u:b9-owner", DateTimeOffset.UtcNow);
        Assert.Equal(1, await verify.OutboxMessages.AsNoTracking().CountAsync(m => m.RunId == runId));
    }

    [Fact]
    public async Task Submit_StaleVersionAfterEdit_IsRejected()
    {
        var runId = await SeedRunAsync();
        var proposalId = await SeedProposalAsync(runId);
        var originalHash = AgentCollaborationContentHash.Compute("İş birliği önerisi — konuk yazı.");
        await using var context = _fixture.CreateContext();
        var service = CreateService(context);
        var edited = "Düzenlenmiş öneri — aylık konuk yazı.";

        // Düzenleme v2'yi onaylar; ardından ESKİ sürüm hash'iyle ikinci onay gelirse reddedilir.
        var editResult = await service.SubmitConfirmationAsync(runId, proposalId,
            AgentCollaborationContentHash.Compute(edited), edited, "u:b9-owner", DateTimeOffset.UtcNow);
        var stale = await CreateService(_fixture.CreateContext())
            .SubmitConfirmationAsync(runId, proposalId, originalHash, null, "u:b9-owner", DateTimeOffset.UtcNow);

        Assert.True(editResult.Accepted);
        Assert.Equal(CollaborateSubmitOutcome.RejectedVersion, stale.Outcome);
    }

    // ------------------------------------------------------------- geçersiz sahiplik

    [Fact]
    public async Task Submit_ForeignOwner_IsRejectedOwner_AndWritesNoAgentMessage()
    {
        var runId = await SeedRunAsync(ownerKey: "u:other-user");
        var proposalId = await SeedProposalAsync(runId, ownerKey: "u:other-user");
        await using var context = _fixture.CreateContext();
        var service = CreateService(context);
        var hash = AgentCollaborationContentHash.Compute("İş birliği önerisi — konuk yazı.");

        var result = await service.SubmitConfirmationAsync(runId, proposalId, hash, null, "u:b9-owner", DateTimeOffset.UtcNow);

        Assert.Equal(CollaborateSubmitOutcome.RejectedOwner, result.Outcome);

        // Yetkisiz çağıran agent kontrol akışına kayıt enjekte edemez.
        await using var verify = _fixture.CreateContext();
        Assert.False(await verify.OutboxMessages.AsNoTracking().AnyAsync(m => m.RunId == runId));
        Assert.Equal(AgentProposalStatus.Proposed,
            (await verify.AgentProposals.AsNoTracking().SingleAsync(p => p.ProposalId == proposalId)).Status);
    }

    [Fact]
    public async Task Submit_UnknownRun_IsRejectedVersion()
    {
        await using var context = _fixture.CreateContext();
        var service = CreateService(context);
        var hash = AgentCollaborationContentHash.Compute("İş birliği önerisi — konuk yazı.");

        var result = await service.SubmitConfirmationAsync(Guid.NewGuid(), Guid.NewGuid(), hash, null, "u:b9-owner", DateTimeOffset.UtcNow);

        Assert.Equal(CollaborateSubmitOutcome.RejectedVersion, result.Outcome);
        Assert.False(await context.OutboxMessages.AsNoTracking().AnyAsync());
    }

    // ------------------------------------------------------------- süre sınırı

    [Fact]
    public async Task Submit_ExpiredProposal_IsRejectedVersion()
    {
        var runId = await SeedRunAsync();
        await using var seed = _fixture.CreateContext();
        var proposalId = Guid.NewGuid();
        seed.AgentProposals.Add(new AgentProposal
        {
            Id = Guid.NewGuid(),
            ProposalId = proposalId,
            Version = 1,
            RunId = runId,
            ArticleId = Guid.NewGuid(),
            ArticleRevision = 3,
            BaseContentHash = new string('b', 64),
            ContentHash = AgentCollaborationContentHash.Compute("İş birliği önerisi — konuk yazı."),
            Summary = "İş birliği önerisi — konuk yazı.",
            OwnerKey = "u:b9-owner",
            ExpiresAt = DateTimeOffset.UtcNow.AddHours(-1), // süresi dolmuş
            Status = AgentProposalStatus.Proposed,
        });
        await seed.SaveChangesAsync();

        await using var context = _fixture.CreateContext();
        var result = await CreateService(context).SubmitConfirmationAsync(runId, proposalId,
            AgentCollaborationContentHash.Compute("İş birliği önerisi — konuk yazı."), null, "u:b9-owner", DateTimeOffset.UtcNow);

        Assert.Equal(CollaborateSubmitOutcome.RejectedVersion, result.Outcome);
        Assert.Contains("süresi", result.RejectionReason);
    }

    // ------------------------------------------------------------- backend kayıt hatası

    [Fact]
    public async Task Submit_EditWhenBackendRecordFails_ReportsNothingAsAccepted()
    {
        // Backend kayıt hatası (gerçek DB yazım hatası): düzenlenen özet kolon
        // sınırını (varchar 8000) aşar; sürüm INSERT'i transaction içinde başa
        // döner. Sözleşme: kayıt yazılamadıysa başarı bildirilmez — onay kaydı
        // ve AgentActionResultV1 TEK transaction'dadır, ikisi de yazılamaz.
        var runId = await SeedRunAsync();
        var proposalId = await SeedProposalAsync(runId);
        await using var context = _fixture.CreateContext();
        var service = CreateService(context);
        var oversizedEdit = new string('x', 8001);
        var oversizedHash = AgentCollaborationContentHash.Compute(oversizedEdit);

        await Assert.ThrowsAsync<DbUpdateException>(() => service.SubmitConfirmationAsync(
            runId, proposalId, oversizedHash, oversizedEdit, "u:b9-owner", DateTimeOffset.UtcNow));

        // Kısmi başarı yok: onay kaydı yok, sürüm satırı yok, outbox'ta mesaj yok.
        await using var verify = _fixture.CreateContext();
        var proposals = await verify.AgentProposals.AsNoTracking()
            .Where(p => p.ProposalId == proposalId).ToListAsync();
        Assert.Single(proposals);
        Assert.Equal(AgentProposalStatus.Proposed, proposals[0].Status);
        Assert.Null(proposals[0].ConfirmedAt);
        Assert.False(await verify.OutboxMessages.AsNoTracking().AnyAsync(m => m.RunId == runId));

        // Aynı çalışma için GEÇERLİ onay sonrasında hâlâ kaydedilebilir (hatadan
        // sonra çalışma bozulmamıştır).
        var validHash = AgentCollaborationContentHash.Compute("İş birliği önerisi — konuk yazı.");
        await using var recovery = _fixture.CreateContext();
        var recoveryResult = await CreateService(recovery).SubmitConfirmationAsync(
            runId, proposalId, validHash, null, "u:b9-owner", DateTimeOffset.UtcNow);
        Assert.True(recoveryResult.Accepted, recoveryResult.RejectionReason);
    }

    // ------------------------------------------------- LLM metni onay kaynağı değildir

    [Fact]
    public async Task Upsert_AloneNeverConfirms_EvenWhenSummaryContainsApprovalLanguage()
    {
        // Projection yalnız KAYIT yazar; özet metnindeki onay ifadesi onay kaynağı değildir.
        var runId = await SeedRunAsync();
        var ownerId = "u:b9-owner";
        await using var context = _fixture.CreateContext();
        var store = new EfAgentCollaborationStore(context);
        var summary = "Kullanıcı onaylıyorum, lütfen bu talebi kaydedin ve gönderin.";
        var proposalId = Guid.NewGuid();

        var upsert = await store.UpsertProposalAsync(new AgentProposalUpsert(
            runId, proposalId, AgentCollaborationContentHash.Compute(summary), summary, ownerId,
            DateTimeOffset.UtcNow.AddHours(168), Guid.NewGuid(), 3, new string('b', 64)));

        Assert.Equal(ProposalUpsertOutcome.Created, upsert.Outcome);

        var stored = await context.AgentProposals.AsNoTracking().SingleAsync(p => p.ProposalId == proposalId);
        Assert.Equal(AgentProposalStatus.Proposed, stored.Status);
        Assert.Null(stored.ConfirmedAt);
        Assert.False(await context.OutboxMessages.AsNoTracking().AnyAsync(m => m.RunId == runId));

        // Aynı sürümün tekrar upsert'i no-op'tur (idempotent projection).
        await using var again = _fixture.CreateContext();
        var repeat = await new EfAgentCollaborationStore(again).UpsertProposalAsync(new AgentProposalUpsert(
            runId, proposalId, AgentCollaborationContentHash.Compute(summary), summary, ownerId,
            DateTimeOffset.UtcNow.AddHours(168), Guid.NewGuid(), 3, new string('b', 64)));
        Assert.Equal(ProposalUpsertOutcome.AlreadyPresent, repeat.Outcome);
        Assert.Equal(1, await again.AgentProposals.AsNoTracking().CountAsync(p => p.ProposalId == proposalId));
    }

    [Fact]
    public async Task Upsert_EditedContent_CreatesNewVersion_KeepsOriginal()
    {
        var runId = await SeedRunAsync();
        var ownerId = "u:b9-owner";
        var summaryV1 = "İş birliği önerisi — konuk yazı.";
        var summaryV2 = "Düzenlenmiş iş birliği önerisi — aylık konuk yazı.";
        var proposalId = Guid.NewGuid();

        await using (var context = _fixture.CreateContext())
        {
            var store = new EfAgentCollaborationStore(context);
            await store.UpsertProposalAsync(new AgentProposalUpsert(
                runId, proposalId, AgentCollaborationContentHash.Compute(summaryV1), summaryV1, ownerId,
                DateTimeOffset.UtcNow.AddHours(168), Guid.NewGuid(), 3, new string('b', 64)));
            await store.UpsertProposalAsync(new AgentProposalUpsert(
                runId, proposalId, AgentCollaborationContentHash.Compute(summaryV2), summaryV2, ownerId,
                DateTimeOffset.UtcNow.AddHours(168), Guid.NewGuid(), 3, new string('b', 64)));
        }

        await using var verify = _fixture.CreateContext();
        var versions = await verify.AgentProposals.AsNoTracking()
            .Where(p => p.ProposalId == proposalId).OrderBy(p => p.Version).ToListAsync();
        Assert.Equal(2, versions.Count);
        Assert.Equal(summaryV1, versions[0].Summary);
        Assert.Equal(summaryV2, versions[1].Summary);
    }
}
