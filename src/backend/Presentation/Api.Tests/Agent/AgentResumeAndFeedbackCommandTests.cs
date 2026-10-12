using BlogApp.Core.Application.Common.Interfaces.Persistence;
using BlogApp.Core.Application.Common.Options;
using BlogApp.Core.Application.Features.AgentFeature.Commands.RecordAgentFeedbackCommand;
using BlogApp.Core.Application.Features.AgentFeature.Commands.ResumeAgentRunCommand;
using BlogApp.Core.Domain.Enums;
using BlogApp.Infrastructure.Messaging;
using BlogApp.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging.Abstractions;
using Microsoft.Extensions.Options;
using Xunit;
using Error = BlogApp.Core.Application.Common.Errors;

namespace BlogApp.Presentation.Api.Tests.Agent;

/// <summary>
/// B10 resume + feedback komutları (plan tablosu satırları: resume "beklenen
/// input/proposal sürümünü doğrulayan devam isteği — B9 sözleşmesi" ve feedback
/// "run sahipliğiyle geri bildirim kaydı"). B9 iş birliği deposu paralel geliştirildiği
/// için resume checkpoint kaydı TEST DOUBLE ile sağlanır (dispatch kuralı); production
/// projection store checkpoint bilinmiyorsa komut üretmez (fail-closed).
/// </summary>
[Collection("agent-b10")]
public class AgentResumeAndFeedbackCommandTests : IAsyncLifetime
{
    private readonly AgentB10DatabaseFixture _fixture;

    public AgentResumeAndFeedbackCommandTests(AgentB10DatabaseFixture fixture) => _fixture = fixture;

    public Task InitializeAsync() => _fixture.ResetAsync();

    public Task DisposeAsync() => Task.CompletedTask;

    // ---- B9 test double'ı: checkpoint referansı bilinen bekleyen resume durumu ----
    private sealed class TestResumeStateStore(Guid runId, AgentResumePendingState state) : IAgentResumeStateStore
    {
        public Task<AgentResumePendingState?> GetPendingAsync(Guid requestRunId, CancellationToken cancellationToken = default) =>
            Task.FromResult(requestRunId == runId ? state : null);
    }

    private static AgentResumePendingState PendingWithCheckpoint(Guid runId, long inputVersion) => new()
    {
        InputVersion = inputVersion,
        CheckpointReference = $"checkpoint/{runId:D}/attempt/1",
    };

    private ResumeAgentRunCommandHandler CreateResumeHandler(
        Guid? userId, IAgentResumeStateStore store) =>
        CreateResumeHandler(userId, store, _fixture.CreateContext());

    private ResumeAgentRunCommandHandler CreateResumeHandler(
        Guid? userId, IAgentResumeStateStore store, AppDbContext context) =>
        new(
            AgentB10TestHost.NewUnitOfWork(context),
            context,
            new TestCurrentUser(userId),
            new EfOutboxWriter(context),
            store,
            Options.Create(new AgentMessagingSettings()),
            NullLogger<ResumeAgentRunCommandHandler>.Instance);

    private RecordAgentFeedbackCommandHandler CreateFeedbackHandler(Guid? userId) =>
        CreateFeedbackHandler(userId, _fixture.CreateContext());

    private RecordAgentFeedbackCommandHandler CreateFeedbackHandler(Guid? userId, AppDbContext context) =>
        new(
            AgentB10TestHost.NewUnitOfWork(context),
            context,
            new TestCurrentUser(userId),
            new ProjectionAgentFeedbackStore(context),
            NullLogger<RecordAgentFeedbackCommandHandler>.Instance);

    // --------------------------------------------------------------- resume

    [Fact]
    public async Task Resume_WithoutPendingState_IsConflict()
    {
        var userId = Guid.NewGuid();
        var run = await AgentB10TestHost.SeedRunAsync(
            _fixture.CreateContext(), ownerKey: $"u:{userId:D}");
        var handler = CreateResumeHandler(
            userId, new ProjectionAgentResumeStateStore(_fixture.CreateContext()));

        var result = await handler.Handle(
            new ResumeAgentRunCommandRequest { RunId = run.Id, ExpectedInputVersion = 1 },
            CancellationToken.None);

        Assert.True(result.IsFailure);
        Assert.Equal(Error.ErrorCategory.Conflict, result.ErrorDetail!.Category);
    }

    [Fact]
    public async Task Resume_WithCheckpointDouble_WritesContractValidOutbox()
    {
        var userId = Guid.NewGuid();
        var run = await AgentB10TestHost.SeedRunAsync(
            _fixture.CreateContext(), ownerKey: $"u:{userId:D}");
        await AgentB10TestHost.SeedAppliedNeedsInputAsync(_fixture.CreateContext(), run.Id, 4);
        var handler = CreateResumeHandler(
            userId, new TestResumeStateStore(run.Id, PendingWithCheckpoint(run.Id, inputVersion: 4)));

        var result = await handler.Handle(
            new ResumeAgentRunCommandRequest { RunId = run.Id, ExpectedInputVersion = 4 },
            CancellationToken.None);

        Assert.True(result.IsSuccess, $"resume başarısız: {result.ErrorDetail?.Category} {result.ErrorDetail?.Message}");
        Assert.Equal("accepted", result.Value!.State);

        await using var context = _fixture.CreateContext();
        var outbox = await context.OutboxMessages
            .SingleAsync(m => m.RunId == run.Id && m.MessageType == "agent.resume.requested");
        Assert.Equal(OutboxStatusPending, outbox.Status);
        Assert.Equal("agent.resume.requested.v1", outbox.RoutingKey);
        // Zarf B1 sözleşmesine uygun: checkpoint_reference + user_ref zorunlu alanlar.
        Assert.Contains("checkpoint_reference", outbox.EnvelopeJson);
        Assert.Contains("user_ref", outbox.EnvelopeJson);
        Assert.Contains("agent.resume.requested", outbox.EnvelopeJson);
    }

    [Fact]
    public async Task Resume_WithStaleExpectedVersion_IsConflict_NoOutbox()
    {
        var userId = Guid.NewGuid();
        var run = await AgentB10TestHost.SeedRunAsync(
            _fixture.CreateContext(), ownerKey: $"u:{userId:D}");
        await AgentB10TestHost.SeedAppliedNeedsInputAsync(_fixture.CreateContext(), run.Id, 7);
        var handler = CreateResumeHandler(
            userId, new TestResumeStateStore(run.Id, PendingWithCheckpoint(run.Id, inputVersion: 7)));

        var result = await handler.Handle(
            new ResumeAgentRunCommandRequest { RunId = run.Id, ExpectedInputVersion = 3 },
            CancellationToken.None);

        Assert.True(result.IsFailure);
        Assert.Equal(Error.ErrorCategory.Conflict, result.ErrorDetail!.Category);
        Assert.False(await AnyResumeOutboxAsync(run.Id));
    }

    [Fact]
    public async Task Resume_WithoutCheckpointRecord_FailClosed_NoOutbox()
    {
        // Production projection store: needs_input VAR ama checkpoint kaydı YOK
        // (B9 deposu beklemede) → komut ÜRETİLMEZ (fail-closed).
        var userId = Guid.NewGuid();
        var run = await AgentB10TestHost.SeedRunAsync(
            _fixture.CreateContext(), ownerKey: $"u:{userId:D}");
        await AgentB10TestHost.SeedAppliedNeedsInputAsync(_fixture.CreateContext(), run.Id, 2);
        var handler = CreateResumeHandler(
            userId, new ProjectionAgentResumeStateStore(_fixture.CreateContext()));

        var result = await handler.Handle(
            new ResumeAgentRunCommandRequest { RunId = run.Id, ExpectedInputVersion = 2 },
            CancellationToken.None);

        Assert.True(result.IsFailure);
        Assert.Equal(Error.ErrorCategory.Conflict, result.ErrorDetail!.Category);
        Assert.False(await AnyResumeOutboxAsync(run.Id));
    }

    [Fact]
    public async Task Resume_OfForeignRun_IsForbidden()
    {
        var run = await AgentB10TestHost.SeedRunAsync(_fixture.CreateContext(), ownerKey: "u:another-b10");
        var handler = CreateResumeHandler(
            Guid.NewGuid(), new ProjectionAgentResumeStateStore(_fixture.CreateContext()));

        var result = await handler.Handle(
            new ResumeAgentRunCommandRequest { RunId = run.Id }, CancellationToken.None);

        Assert.True(result.IsFailure);
        Assert.Equal(Error.ErrorCategory.Forbidden, result.ErrorDetail!.Category);
    }

    [Fact]
    public async Task Resume_OfTerminalRun_IsRejected()
    {
        var userId = Guid.NewGuid();
        var run = await AgentB10TestHost.SeedRunAsync(
            _fixture.CreateContext(), ownerKey: $"u:{userId:D}",
            status: AgentRunStatus.Completed, terminalAt: DateTime.UtcNow);
        var handler = CreateResumeHandler(
            userId, new TestResumeStateStore(run.Id, PendingWithCheckpoint(run.Id, 1)));

        var result = await handler.Handle(
            new ResumeAgentRunCommandRequest { RunId = run.Id, ExpectedInputVersion = 1 },
            CancellationToken.None);

        Assert.True(result.IsFailure);
        Assert.Equal(Error.ErrorCategory.Domain, result.ErrorDetail!.Category);
    }

    // -------------------------------------------------------------- feedback

    [Fact]
    public async Task Feedback_RecordsOnceAndReplaysSameKey()
    {
        var userId = Guid.NewGuid();
        var run = await AgentB10TestHost.SeedRunAsync(
            _fixture.CreateContext(), ownerKey: $"u:{userId:D}");
        var handler = CreateFeedbackHandler(userId);

        var first = await handler.Handle(
            new RecordAgentFeedbackCommandRequest
            {
                RunId = run.Id,
                Rating = 5,
                Comment = "Çok yardımcı oldu",
                FeedbackKey = "fb-key-1",
            }, CancellationToken.None);
        Assert.True(first.IsSuccess);
        Assert.Equal("recorded", first.Value!.State);

        // Çift tık / ağ tekrarı: aynı anahtar YENİ kayıt üretmez (idempotent replay).
        var second = await handler.Handle(
            new RecordAgentFeedbackCommandRequest
            {
                RunId = run.Id,
                Rating = 5,
                Comment = "Çok yardımcı oldu",
                FeedbackKey = "fb-key-1",
            }, CancellationToken.None);
        Assert.True(second.IsSuccess);
        Assert.Equal("replay", second.Value!.State);

        await using var context = _fixture.CreateContext();
        var feedbackRows = await context.AgentEventInboxes
            .Where(i => i.ConsumerName == "backend-agent-feedback" && i.RunId == run.Id)
            .ToListAsync();
        Assert.Single(feedbackRows);
        Assert.Contains("5", feedbackRows[0].Detail);
    }

    [Fact]
    public async Task Feedback_OfForeignRun_IsForbidden()
    {
        var run = await AgentB10TestHost.SeedRunAsync(_fixture.CreateContext(), ownerKey: "u:another-b10");

        var result = await CreateFeedbackHandler(Guid.NewGuid()).Handle(
            new RecordAgentFeedbackCommandRequest
            {
                RunId = run.Id,
                Rating = 4,
                FeedbackKey = "fb-foreign",
            }, CancellationToken.None);

        Assert.True(result.IsFailure);
        Assert.Equal(Error.ErrorCategory.Forbidden, result.ErrorDetail!.Category);
    }

    [Theory]
    [InlineData(0)]
    [InlineData(6)]
    public async Task Feedback_WithInvalidRating_IsValidation(int rating)
    {
        var userId = Guid.NewGuid();
        var run = await AgentB10TestHost.SeedRunAsync(
            _fixture.CreateContext(), ownerKey: $"u:{userId:D}");

        var result = await CreateFeedbackHandler(userId).Handle(
            new RecordAgentFeedbackCommandRequest
            {
                RunId = run.Id,
                Rating = rating,
                FeedbackKey = "fb-invalid",
            }, CancellationToken.None);

        Assert.True(result.IsFailure);
        Assert.Equal(Error.ErrorCategory.Validation, result.ErrorDetail!.Category);
    }

    private async Task<bool> AnyResumeOutboxAsync(Guid runId)
    {
        await using var context = _fixture.CreateContext();
        return await context.OutboxMessages.AnyAsync(m => m.RunId == runId && m.MessageType == "agent.resume.requested");
    }

    private static readonly BlogApp.Core.Domain.Enums.AgentOutboxStatus OutboxStatusPending =
        BlogApp.Core.Domain.Enums.AgentOutboxStatus.Pending;
}
