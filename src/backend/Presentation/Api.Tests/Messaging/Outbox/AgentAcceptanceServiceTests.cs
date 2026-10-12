using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using BlogApp.Core.Application.Common.Interfaces.Services;
using BlogApp.Core.Application.Common.Messaging;
using BlogApp.Core.Application.Features.AgentFeature.Commands.AcceptAgentRunCommand;
using BlogApp.Core.Application.Common.Options;
using BlogApp.Core.Domain.Entities;
using BlogApp.Core.Domain.Enums;
using BlogApp.Infrastructure.Messaging;
using BlogApp.Infrastructure.Persistence;
using BlogApp.Infrastructure.Persistence.Repositories;
using Microsoft.Extensions.Logging.Abstractions;
using Microsoft.Extensions.Options;
using Xunit;
using Error = BlogApp.Core.Application.Common.Errors;

namespace BlogApp.Presentation.Api.Tests.Messaging.Outbox;

/// <summary>
/// B3 iş kabulü senaryoları — gerçek Postgres (koşum başına benzersiz izole
/// scratch DB, blogdb_b3tests_*) üzerinde: oturum doğrulama, makale
/// erişim/limit, idempotency (replay + çakışma), turn_sequence.
/// </summary>
[Collection("agent-rabbitmq-outbox")]
public class AgentAcceptanceServiceTests : IAsyncLifetime
{
    private readonly AgentOutboxDatabaseFixture _fixture;

    public AgentAcceptanceServiceTests(AgentOutboxDatabaseFixture fixture)
    {
        _fixture = fixture;
    }

    public Task InitializeAsync() => _fixture.ResetAsync();

    public Task DisposeAsync() => Task.CompletedTask;

    private AcceptAgentRunCommandHandler CreateHandler(Guid? userId, bool allowGuestRuns = true)
    {
        var context = _fixture.CreateContext();
        return new AcceptAgentRunCommandHandler(
            new UnitOfWork(context),
            context,
            new TestCurrentUser(userId),
            new EfOutboxWriter(context),
            Options.Create(new AgentAcceptanceSettings { AllowGuestRuns = allowGuestRuns, MaxActiveRunsPerOwner = 2 }),
            Options.Create(new AgentMessagingSettings()),
            NullLogger<AcceptAgentRunCommandHandler>.Instance);
    }

    private static AcceptAgentRunCommandRequest ValidRequest(string idempotencyKey = "key-0001", Guid? articleId = null) =>
        new()
        {
            Question = "Bu makaledeki ana fikir nedir?",
            Language = "tr",
            ModePreference = "auto",
            BudgetProfile = "standard",
            ArticleId = articleId,
            IdempotencyKey = idempotencyKey,
        };

    // ------------------------------------------------------------- oturum

    [Fact]
    public async Task Accept_WithoutAnyIdentity_IsUnauthorized()
    {
        var handler = CreateHandler(userId: null);

        var result = await handler.Handle(ValidRequest(), CancellationToken.None);

        Assert.True(result.IsFailure);
        Assert.Equal(Error.ErrorCategory.Unauthorized, result.ErrorDetail!.Category);
    }

    [Fact]
    public async Task Accept_GuestSession_PersistsRunWithGuestOwner()
    {
        // misafir kimliği Presentation'ın ürettiği sunucu tarafı oturumdan komuta taşınır (K5)
        var handler = CreateHandler(userId: null);

        var result = await handler.Handle(ValidRequest() with { GuestSessionId = "guest-abc123" }, CancellationToken.None);

        Assert.True(result.IsSuccess, result.ErrorDetail?.ToString() ?? "bilinmeyen hata");
        await using var context = _fixture.CreateContext();
        var run = context.AgentRuns.Single(r => r.Id == result.Value!.RunId);
        Assert.Equal("g:guest-abc123", run.OwnerKey);
        Assert.Null(run.OwnerUserId);
        Assert.Equal(AgentRunStatus.Accepted, run.Status);
    }

    [Fact]
    public async Task Accept_GuestSession_WhenGuestRunsDisabled_IsForbidden()
    {
        var handler = CreateHandler(userId: null, allowGuestRuns: false);

        var result = await handler.Handle(ValidRequest() with { GuestSessionId = "guest-xyz" }, CancellationToken.None);

        Assert.True(result.IsFailure);
        Assert.Equal(Error.ErrorCategory.Forbidden, result.ErrorDetail!.Category);
        await using var context = _fixture.CreateContext();
        Assert.False(context.AgentRuns.Any());
    }

    // ------------------------------------------------------------- makale erişimi

    [Fact]
    public async Task Accept_WithPublishedArticle_RecordsImmutableSnapshotWithContentHash()
    {
        var user = await _fixture.SeedUserAsync();
        var post = await _fixture.SeedPostAsync(user.Id, "B3 Kabul Testi", PostStatus.Published);
        var handler = CreateHandler(user.Id);

        var result = await handler.Handle(ValidRequest(articleId: post.Id), CancellationToken.None);

        Assert.True(result.IsSuccess, result.ErrorDetail?.ToString() ?? "bilinmeyen hata");
        await using var context = _fixture.CreateContext();
        var run = context.AgentRuns.Single(r => r.Id == result.Value!.RunId);

        var expectedHash = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(post.Content))).ToLowerInvariant();
        Assert.Equal(post.Id, run.ArticleId);
        Assert.Equal(expectedHash, run.ArticleContentHash);
        Assert.Contains(expectedHash, run.ContextSnapshotJson);
        Assert.StartsWith($"agent-run/{run.Id:D}/turn/", run.ContextSnapshotReference);

        // snapshot'ta yayınlanma zamanı UTC ISO biçiminde (D008 anlam sözlüğü)
        Assert.Contains("published_at", run.ContextSnapshotJson);
    }

    [Fact]
    public async Task Accept_WithPublishedArticle_ExecuteCommandCarriesArticleTriple()
    {
        // W5 bulgusu 4i: execute komutu makale bağlamını article_id/article_revision/
        // article_content_hash ÜÇLÜSÜ halinde taşır (B1 all-or-none); worker'ın B8
        // stale komut guard'ı bu üçlüyle çalışır. Kabul snapshot'ı da revision'ı yazar.
        var user = await _fixture.SeedUserAsync("triple-user");
        var post = await _fixture.SeedPostAsync(user.Id, "B3 Üçlü Testi", PostStatus.Published, contentRevision: 7);
        var handler = CreateHandler(user.Id);

        var result = await handler.Handle(ValidRequest("triple-1", post.Id), CancellationToken.None);

        Assert.True(result.IsSuccess, result.ErrorDetail?.ToString() ?? "bilinmeyen hata");

        await using var context = _fixture.CreateContext();
        var message = context.OutboxMessages.Single();
        var payload = JsonDocument.Parse(message.EnvelopeJson).RootElement.GetProperty("payload");

        Assert.Equal(post.Id.ToString("D"), payload.GetProperty("article_id").GetString());
        Assert.Equal(7, payload.GetProperty("article_revision").GetInt64());
        var expectedHash = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(post.Content))).ToLowerInvariant();
        Assert.Equal(expectedHash, payload.GetProperty("article_content_hash").GetString());

        // Saklanan zarf üçlüyle B1 sözleşme doğrulayıcısından geçer.
        var validation = new AgentContractValidator(new AgentMessagingSettings()).Validate(message.EnvelopeJson);
        Assert.True(validation.IsValid, $"zarf doğrulaması: {validation.Error?.ToString()}");

        // Kabul snapshot'ı revizyonu yazar (yalnız hash/published_at değil).
        var run = context.AgentRuns.Single(r => r.Id == result.Value!.RunId);
        var snapshot = JsonDocument.Parse(run.ContextSnapshotJson).RootElement;
        Assert.Equal("7", snapshot.GetProperty("article_revision").GetString());
    }

    [Fact]
    public void Compose_WithPartialArticleTriple_IsRejectedWithoutEnvelope()
    {
        // all-or-none: eksik üçlü B1 sözleşme ihlalidir; composer zarf ÜRETMEZ.
        Assert.Throws<ArgumentException>(() => AgentCommandEnvelopeComposer.ComposeExecutionRequested(
            Guid.NewGuid(),
            Guid.NewGuid(),
            Guid.NewGuid().ToString("D"),
            DateTimeOffset.UtcNow,
            DateTimeOffset.UtcNow.AddMinutes(5),
            producer: "backend-net",
            userRef: "u:00000000-0000-0000-0000-000000000001",
            question: "soru",
            language: "tr",
            modePreference: "fast",
            budgetProfile: "standard",
            contextSnapshotReference: null,
            selectedText: null,
            articleId: "00000000-0000-0000-0000-000000000002",
            articleRevision: null,
            articleContentHash: new string('a', 64)));
    }

    [Fact]
    public async Task Accept_WithUnpublishedArticle_IsForbidden()
    {
        var user = await _fixture.SeedUserAsync();
        var draft = await _fixture.SeedPostAsync(user.Id, "B3 Taslak", PostStatus.Draft);
        var handler = CreateHandler(user.Id);

        var result = await handler.Handle(ValidRequest(articleId: draft.Id), CancellationToken.None);

        Assert.True(result.IsFailure);
        Assert.Equal(Error.ErrorCategory.Forbidden, result.ErrorDetail!.Category);
        await using var context = _fixture.CreateContext();
        Assert.False(context.AgentRuns.Any());
        Assert.False(context.OutboxMessages.Any());
    }

    // ------------------------------------------------------------- idempotency

    [Fact]
    public async Task Accept_SameKeySamePayload_ReplaysExistingRunWithoutNewRows()
    {
        var user = await _fixture.SeedUserAsync();
        var handler = CreateHandler(user.Id);

        var first = await handler.Handle(ValidRequest("idem-1"), CancellationToken.None);
        var second = await handler.Handle(ValidRequest("idem-1"), CancellationToken.None);

        Assert.True(first.IsSuccess);
        Assert.True(second.IsSuccess);
        Assert.False(first.Value!.Replay);
        Assert.True(second.Value!.Replay);
        Assert.Equal(first.Value!.RunId, second.Value!.RunId);
        Assert.Equal(first.Value!.TurnSequence, second.Value!.TurnSequence);

        await using var context = _fixture.CreateContext();
        Assert.Equal(1, context.AgentRuns.Count());
        Assert.Equal(1, context.OutboxMessages.Count());
    }

    [Fact]
    public async Task Accept_SameKeyDifferentPayload_Conflicts()
    {
        var user = await _fixture.SeedUserAsync();
        var handler = CreateHandler(user.Id);

        var first = await handler.Handle(ValidRequest("idem-2"), CancellationToken.None);
        var request = ValidRequest("idem-2") with { Question = "Farklı bir soru?" };
        var second = await handler.Handle(request, CancellationToken.None);

        Assert.True(first.IsSuccess);
        Assert.True(second.IsFailure);
        Assert.Equal(Error.ErrorCategory.Conflict, second.ErrorDetail!.Category);

        await using var context = _fixture.CreateContext();
        Assert.Equal(1, context.AgentRuns.Count());
        Assert.Equal(1, context.OutboxMessages.Count());
    }

    // ------------------------------------------------------------- konuşma/tur

    [Fact]
    public async Task Accept_FollowUpInSameConversation_IncrementsTurnSequence()
    {
        var user = await _fixture.SeedUserAsync();
        var handler = CreateHandler(user.Id);

        var first = await handler.Handle(ValidRequest("turn-1"), CancellationToken.None);
        var followUp = ValidRequest("turn-2") with { ConversationId = first.Value!.ConversationId };
        var second = await handler.Handle(followUp, CancellationToken.None);

        Assert.True(second.IsSuccess);
        Assert.Equal(first.Value!.ConversationId, second.Value!.ConversationId);
        Assert.Equal(1, first.Value!.TurnSequence);
        Assert.Equal(2, second.Value!.TurnSequence);

        await using var context = _fixture.CreateContext();
        var runs = context.AgentRuns.OrderBy(r => r.TurnSequence).ToList();
        Assert.Equal([1L, 2L], runs.Select(r => r.TurnSequence));
    }

    [Fact]
    public async Task Accept_ForeignConversation_IsForbidden()
    {
        var owner = await _fixture.SeedUserAsync("owner-a");
        var intruder = await _fixture.SeedUserAsync("owner-b");
        var ownerHandler = CreateHandler(owner.Id);
        var intruderHandler = CreateHandler(intruder.Id);

        var first = await ownerHandler.Handle(ValidRequest("own-1"), CancellationToken.None);
        var intrude = ValidRequest("own-2") with { ConversationId = first.Value!.ConversationId };
        var second = await intruderHandler.Handle(intrude, CancellationToken.None);

        Assert.True(first.IsSuccess);
        Assert.True(second.IsFailure);
        Assert.Equal(Error.ErrorCategory.Forbidden, second.ErrorDetail!.Category);
    }

    // ------------------------------------------------------------- limit

    [Fact]
    public async Task Accept_WhenActiveRunLimitReached_IsRejected()
    {
        var user = await _fixture.SeedUserAsync("limit-user");
        var handler = CreateHandler(user.Id); // MaxActiveRunsPerOwner = 2

        var first = await handler.Handle(ValidRequest("limit-1"), CancellationToken.None);
        var second = await handler.Handle(ValidRequest("limit-2"), CancellationToken.None);
        var third = await handler.Handle(ValidRequest("limit-3"), CancellationToken.None);

        Assert.True(first.IsSuccess);
        Assert.True(second.IsSuccess);
        Assert.True(third.IsFailure);
        Assert.Equal(Error.ErrorCategory.Domain, third.ErrorDetail!.Category);

        await using var context = _fixture.CreateContext();
        Assert.Equal(2, context.AgentRuns.Count());
        Assert.Equal(2, context.OutboxMessages.Count());
    }

    // ------------------------------------------------------------- outbox sözleşmesi

    [Fact]
    public async Task Accept_PersistedOutboxEnvelope_PassesB1ContractValidatorAndRouting()
    {
        var user = await _fixture.SeedUserAsync("contract-user");
        var handler = CreateHandler(user.Id);

        var result = await handler.Handle(ValidRequest("contract-1"), CancellationToken.None);
        Assert.True(result.IsSuccess, result.ErrorDetail?.ToString() ?? "bilinmeyen hata");

        await using var context = _fixture.CreateContext();
        var message = context.OutboxMessages.Single();

        Assert.Equal(AgentMessageTypes.ExecutionRequested, message.MessageType);
        Assert.Equal(AgentMessageTypeRegistry.CommandsExchange, message.Exchange);
        Assert.Equal("agent.execute.requested.v1", message.RoutingKey);
        Assert.Equal(AgentOutboxStatus.Pending, message.Status);
        Assert.Equal(result.Value!.RunId, message.RunId);
        Assert.Equal(0, message.AttemptCount);

        // saklanan zarf, B1 doğrulayıcısından geçer (commit öncesi doğrulamanın kalıcı kanıtı)
        var validation = new AgentContractValidator(new AgentMessagingSettings()).Validate(message.EnvelopeJson);
        Assert.True(validation.IsValid, $"zarf doğrulaması: {validation.Error?.ToString()}");

        var envelope = validation.Envelope!;
        Assert.Equal(message.MessageId, envelope.MessageId);
        Assert.Equal(result.Value.RunId.ToString("D"), envelope.RunId);
        Assert.Equal(result.Value.ConversationId.ToString("D"), envelope.ConversationId);
        Assert.Equal("backend-net", envelope.Producer);
        Assert.NotNull(envelope.DeadlineAt);
        Assert.True(envelope.DeadlineAt != null);
    }

    [Fact]
    public async Task Accept_AgentRunDeadline_IsSetByBackendPerMode()
    {
        var user = await _fixture.SeedUserAsync("deadline-user");
        var handler = CreateHandler(user.Id);

        var before = DateTime.UtcNow;
        var result = await handler.Handle(ValidRequest("dl-1") with { ModePreference = "fast" }, CancellationToken.None);
        var after = DateTime.UtcNow;

        Assert.True(result.IsSuccess, result.ErrorDetail?.ToString() ?? "bilinmeyen hata");
        await using var context = _fixture.CreateContext();
        var run = context.AgentRuns.Single(r => r.Id == result.Value!.RunId);
        Assert.InRange(run.DeadlineAt, before.AddMinutes(2).AddSeconds(-5), after.AddMinutes(2).AddSeconds(5));
    }

    // ------------------------------------------------------------- yardımcılar

    private sealed class TestCurrentUser(Guid? userId) : ICurrentUserService
    {
        public Guid? UserId => userId;
        public string? UserName => userId is null ? null : "test-user";
        public string? Email => null;
        public string? CorrelationId => null;
        public bool IsAuthenticated => userId is not null;
        public bool IsInRole(string role) => false;
    }
}
