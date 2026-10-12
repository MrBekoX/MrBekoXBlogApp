using BlogApp.Core.Application.Common.Interfaces.Services;
using BlogApp.Core.Application.Common.Messaging;
using BlogApp.Core.Application.Common.Options;
using BlogApp.Core.Application.Features.AgentFeature.Commands.CancelAgentRunCommand;
using BlogApp.Core.Domain.Entities;
using BlogApp.Core.Domain.Enums;
using BlogApp.Infrastructure.Messaging;
using BlogApp.Infrastructure.Persistence;
using BlogApp.Infrastructure.Persistence.Repositories;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging.Abstractions;
using Microsoft.Extensions.Options;
using Xunit;
using Error = BlogApp.Core.Application.Common.Errors;

namespace BlogApp.Presentation.Api.Tests.Messaging.Cancel;

/// <summary>
/// B7 cancel komut senaryoları (plan satır 427) — gerçek Postgres üzerinde:
/// sahiplik, terminal kaydı (already_terminal), idempotent replay, outbox
/// sözleşme doğrulaması. Cancel intent kaydı terminal değildir; terminal
/// agent.run.cancelled projection'ıyla gelir (B5).
/// </summary>
[Collection("agent-b7-control")]
public class AgentCancelRunCommandTests : IAsyncLifetime
{
    private readonly AgentControlDatabaseFixture _fixture;

    public AgentCancelRunCommandTests(AgentControlDatabaseFixture fixture)
    {
        _fixture = fixture;
    }

    public Task InitializeAsync() => _fixture.ResetAsync();

    public Task DisposeAsync() => Task.CompletedTask;

    private CancelAgentRunCommandHandler CreateHandler(Guid? userId)
    {
        var context = _fixture.CreateContext();
        return new CancelAgentRunCommandHandler(
            new UnitOfWork(context),
            context,
            new TestCurrentUser(userId),
            new EfOutboxWriter(context),
            Options.Create(new AgentMessagingSettings()),
            NullLogger<CancelAgentRunCommandHandler>.Instance);
    }

    private static CancelAgentRunCommandRequest ValidRequest(Guid runId, string? reason = "kullanıcı isteği") =>
        new() { RunId = runId, Reason = reason };

    private async Task<AgentRun> SeedRunAsync(Guid? runId = null, string ownerKey = "u:b7-user", AgentRunStatus status = AgentRunStatus.Accepted)
    {
        await using var context = _fixture.CreateContext();
        var run = new AgentRun
        {
            Id = runId ?? Guid.NewGuid(),
            ConversationId = Guid.NewGuid(),
            TurnSequence = 1,
            OwnerKey = ownerKey,
            IdempotencyKey = $"idem-{Guid.NewGuid():N}",
            IdempotencyPayloadHash = new string('a', 64),
            Status = status,
            Question = "B7 test sorusu",
            Language = "tr",
            ModePreference = "auto",
            BudgetProfile = "default",
            ContextSnapshotReference = $"agent-run/{runId}/turn/1",
            ContextSnapshotJson = """{"question":"B7 test sorusu"}""",
            DeadlineAt = DateTime.UtcNow.AddMinutes(10),
            AcceptedAt = DateTime.UtcNow,
        };
        context.AgentRuns.Add(run);
        await context.SaveChangesAsync();
        return run;
    }

    // ------------------------------------------------------------- oturum/sahiplik

    [Fact]
    public async Task Cancel_WithoutAnyIdentity_IsUnauthorized()
    {
        var run = await SeedRunAsync();
        var handler = CreateHandler(userId: null);

        var result = await handler.Handle(ValidRequest(run.Id), CancellationToken.None);

        Assert.True(result.IsFailure);
        Assert.Equal(Error.ErrorCategory.Unauthorized, result.ErrorDetail!.Category);
    }

    [Fact]
    public async Task Cancel_UnknownRun_IsNotFound()
    {
        var handler = CreateHandler(Guid.NewGuid());

        var result = await handler.Handle(ValidRequest(Guid.NewGuid()), CancellationToken.None);

        Assert.True(result.IsFailure);
        Assert.Equal(Error.ErrorCategory.NotFound, result.ErrorDetail!.Category);
    }

    [Fact]
    public async Task Cancel_ForeignRun_IsForbidden()
    {
        var run = await SeedRunAsync(ownerKey: "u:another-user");
        var handler = CreateHandler(Guid.NewGuid()); // başka kullanıcı

        var result = await handler.Handle(ValidRequest(run.Id), CancellationToken.None);

        Assert.True(result.IsFailure);
        Assert.Equal(Error.ErrorCategory.Forbidden, result.ErrorDetail!.Category);
    }

    [Fact]
    public async Task Cancel_GuestOwnedRun_WithMatchingGuestSession_IsAccepted()
    {
        var run = await SeedRunAsync(ownerKey: "g:guest-b7");
        await using var context = _fixture.CreateContext();
        var handler = new CancelAgentRunCommandHandler(
            new UnitOfWork(context),
            context,
            new TestCurrentUser(userId: null),
            new EfOutboxWriter(context),
            Options.Create(new AgentMessagingSettings()),
            NullLogger<CancelAgentRunCommandHandler>.Instance);

        var result = await handler.Handle(
            ValidRequest(run.Id) with { GuestSessionId = "guest-b7" }, CancellationToken.None);

        Assert.True(result.IsSuccess, result.ErrorDetail?.Message);
        Assert.Equal("requested", result.Value!.Outcome);
    }

    // ------------------------------------------------------------- terminal/idempotency

    [Fact]
    public async Task Cancel_TerminalRun_ReturnsAlreadyTerminal_WritesNoOutbox()
    {
        var userId = Guid.NewGuid();
        var run = await SeedRunAsync(ownerKey: $"u:{userId:D}", status: AgentRunStatus.Cancelled);
        var handler = CreateHandler(userId);

        var result = await handler.Handle(ValidRequest(run.Id), CancellationToken.None);

        Assert.True(result.IsSuccess);
        Assert.Equal("already_terminal", result.Value!.Outcome); // geç cancel terminali geri götürmez
        await using var context = _fixture.CreateContext();
        Assert.False(await context.OutboxMessages.AnyAsync(m => m.RunId == run.Id));
    }

    [Fact]
    public async Task Cancel_ActiveRun_WritesContractValidCancelOutbox()
    {
        var userId = Guid.NewGuid();
        var run = await SeedRunAsync(ownerKey: $"u:{userId:D}");
        var handler = CreateHandler(userId);

        var result = await handler.Handle(ValidRequest(run.Id, reason: "artık gerekmiyor"), CancellationToken.None);

        Assert.True(result.IsSuccess, result.ErrorDetail?.Message);
        Assert.Equal("requested", result.Value!.Outcome);

        await using var context = _fixture.CreateContext();
        var outbox = await context.OutboxMessages.SingleAsync(m => m.RunId == run.Id);
        Assert.Equal(AgentMessageTypes.CancellationRequested, outbox.MessageType);
        Assert.Equal("agent.cancel.requested.v1", outbox.RoutingKey);
        Assert.Equal(AgentOutboxStatus.Pending, outbox.Status);

        // Zarf commit'ten önce doğrulandı (B3 deseni); kayıtta hâlâ geçerli.
        var validation = new AgentContractValidator(new AgentMessagingSettings()).Validate(outbox.EnvelopeJson);
        Assert.True(validation.IsValid);

        // Kalıcı niyet kaydı: RunId + tür + Pending (backend cancel intent'i).
        Assert.Equal(run.Id.ToString("D"), validation.Envelope!.RunId);
    }

    [Fact]
    public async Task Cancel_SecondCall_IsIdempotentReplay_WithoutDuplicateOutbox()
    {
        var userId = Guid.NewGuid();
        var run = await SeedRunAsync(ownerKey: $"u:{userId:D}");
        var handler = CreateHandler(userId);

        var first = await handler.Handle(ValidRequest(run.Id), CancellationToken.None);
        var second = await handler.Handle(ValidRequest(run.Id), CancellationToken.None);

        Assert.True(first.IsSuccess);
        Assert.True(second.IsSuccess);
        Assert.Equal("requested", first.Value!.Outcome);
        Assert.Equal("replay", second.Value!.Outcome); // açık cancel komutu var: yeni kayıt yazılmaz

        await using var context = _fixture.CreateContext();
        Assert.Equal(1, await context.OutboxMessages.CountAsync(m => m.RunId == run.Id));
    }

    [Fact]
    public async Task Cancel_ReasonOverContractLimit_IsRejected()
    {
        var userId = Guid.NewGuid();
        var run = await SeedRunAsync(ownerKey: $"u:{userId:D}");
        var handler = CreateHandler(userId);

        var result = await handler.Handle(
            ValidRequest(run.Id, reason: new string('x', 2001)), CancellationToken.None);

        Assert.True(result.IsFailure);
        Assert.Equal(Error.ErrorCategory.Domain, result.ErrorDetail!.Category);
        await using var context = _fixture.CreateContext();
        Assert.False(await context.OutboxMessages.AnyAsync(m => m.RunId == run.Id));
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
