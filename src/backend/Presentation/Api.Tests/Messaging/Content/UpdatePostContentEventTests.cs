using BlogApp.BuildingBlocks.Abstractions;
using BlogApp.Core.Application.Common.Interfaces.Persistence;
using BlogApp.Core.Application.Common.Interfaces.Services;
using BlogApp.Core.Application.Common.Messaging;
using BlogApp.Core.Application.Common.Models;
using BlogApp.Core.Application.Features.PostFeature.Commands.UpdatePostCommand;
using BlogApp.Core.Application.Features.PostFeature.DTOs;
using BlogApp.Core.Application.Features.PostFeature.Rules;
using BlogApp.Core.Domain.Entities;
using BlogApp.Core.Domain.Enums;
using BlogApp.Core.Domain.ValueObjects;
using BlogApp.Infrastructure.Messaging;
using BlogApp.Infrastructure.Persistence;
using BlogApp.Infrastructure.Persistence.Repositories;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging.Abstractions;
using Microsoft.Extensions.Options;
using Xunit;
using Result = BlogApp.Core.Application.Common.Models.Result;

namespace BlogApp.Presentation.Api.Tests.Messaging.Content;

/// <summary>
/// B8 makale handler kablolama kanıtı: UpdatePostCommandHandler'ın additive içerik olay
/// satırları gerçek Postgres üzerinde uçtan uca doğrulanır — yayımlanmış makalenin içeriği
/// değişirse tek SaveChanges ile revision+olay yazılır; taslakta hiçbir şey yazılmaz.
/// </summary>
[Collection("agent-content-sync-b8")]
public class UpdatePostContentEventTests : IAsyncLifetime
{
    private readonly ContentSyncDatabaseFixture _fixture;

    public UpdatePostContentEventTests(ContentSyncDatabaseFixture fixture)
    {
        _fixture = fixture;
    }

    public Task InitializeAsync() => _fixture.ResetAsync();

    public Task DisposeAsync() => Task.CompletedTask;

    private UpdatePostCommandHandler CreateHandler(Guid userId)
    {
        var context = _fixture.CreateContext();
        return new UpdatePostCommandHandler(
            new UnitOfWork(context),
            new TestCurrentUser(userId),
            new AlwaysPassBusinessRules(),
            new FakeTagService(),
            new NoopCacheService(),
            new IdentitySanitizer(),
            new AgentContentEventService(
                new EfOutboxWriter(context),
                Options.Create(new BlogApp.Core.Application.Common.Options.AgentMessagingSettings()),
                NullLogger<AgentContentEventService>.Instance));
    }

    [Fact]
    public async Task UpdatePublishedContent_WritesRevisionAndEventInOneCommit()
    {
        var user = await _fixture.SeedUserAsync();
        var post = await _fixture.SeedPostAsync(user.Id, "Handler Published", PostStatus.Published, contentRevision: 1);

        var handler = CreateHandler(user.Id);
        var request = new UpdatePostCommandRequest
        {
            UpdatePostCommandRequestDto = new UpdatePostCommandDto
            {
                Id = post.Id,
                Title = post.Title,
                Content = "# Handler Published\n\nGuncel markdown icerik.",
                Excerpt = null,
                Status = "Published",
                TagNames = [],
                CategoryIds = [],
                IsFeatured = false,
            },
        };

        var result = await handler.Handle(request, CancellationToken.None);
        Assert.True(result.IsSuccess, result.ErrorDetail?.ToString() ?? "bilinmeyen hata");

        await using var verify = _fixture.CreateContext();
        var saved = await verify.Posts.AsNoTracking().SingleAsync(p => p.Id == post.Id);
        Assert.Equal(2, saved.ContentRevision);
        var message = await verify.OutboxMessages.AsNoTracking().SingleAsync();
        Assert.Equal("content.article.changed", message.MessageType);
    }

    [Fact]
    public async Task UpdateDraft_WritesNoEvent()
    {
        var user = await _fixture.SeedUserAsync();
        var post = await _fixture.SeedPostAsync(user.Id, "Handler Draft", PostStatus.Draft);

        var handler = CreateHandler(user.Id);
        var request = new UpdatePostCommandRequest
        {
            UpdatePostCommandRequestDto = new UpdatePostCommandDto
            {
                Id = post.Id,
                Title = post.Title,
                Content = "# Handler Draft\n\nTaslak icerik.",
                Status = "Draft",
                TagNames = [],
                CategoryIds = [],
            },
        };

        var result = await handler.Handle(request, CancellationToken.None);
        Assert.True(result.IsSuccess, result.ErrorDetail?.ToString() ?? "bilinmeyen hata");

        await using var verify = _fixture.CreateContext();
        Assert.Equal(0, (await verify.Posts.AsNoTracking().SingleAsync(p => p.Id == post.Id)).ContentRevision);
        Assert.False(await verify.OutboxMessages.AnyAsync());
    }

    // ------------------------------------------------------------- test double'lar

    private sealed class TestCurrentUser(Guid userId) : ICurrentUserService
    {
        public Guid? UserId { get; } = userId;
        public string? UserName => "b8-test-user";
        public string? Email => "b8-test-user@example.com";
        public string? CorrelationId => "b8-test-correlation";
        public bool IsAuthenticated => true;
        public bool IsInRole(string roleName) => roleName is "Admin" or "Editor";
    }

    private sealed class AlwaysPassBusinessRules : IPostBusinessRules
    {
        public Task<Result> CheckPostExistsAsync(Guid postId) => Task.FromResult(Result.Success());
        public Task<Result> CheckUserCanEditPostAsync(Guid postId, Guid userId) => Task.FromResult(Result.Success());
        public Task<Result> CheckUserCanDeletePostAsync(Guid postId, Guid userId) => Task.FromResult(Result.Success());
        public Task<Result> CheckPostIsNotPublishedAsync(Guid postId) => Task.FromResult(Result.Success());
    }

    private sealed class FakeTagService : ITagService
    {
        public Task<List<Tag>> GetOrCreateTagsAsync(IEnumerable<string> tagNames, CancellationToken cancellationToken = default) =>
            Task.FromResult(new List<Tag>());
    }

    private sealed class IdentitySanitizer : IHtmlSanitizerService
    {
        public string? Sanitize(string? html) => html;
    }

    private sealed class NoopCacheService : ICacheService
    {
        public Task<T?> GetAsync<T>(string key, CancellationToken cancellationToken = default) => Task.FromResult(default(T));
        public Task SetAsync<T>(string key, T value, TimeSpan? expiration = null, CancellationToken cancellationToken = default) => Task.CompletedTask;
        public Task RemoveAsync(string key, CancellationToken cancellationToken = default) => Task.CompletedTask;
        public Task<bool> ExistsAsync(string key, CancellationToken cancellationToken = default) => Task.FromResult(false);
        public Task<T> GetOrSetAsync<T>(string key, Func<Task<T>> factory, TimeSpan? expiration = null, CancellationToken cancellationToken = default) => factory();
        public Task RemoveByPrefixAsync(string prefix, CancellationToken cancellationToken = default) => Task.CompletedTask;
        public Task<long> GetGroupVersionAsync(string groupName, CancellationToken cancellationToken = default) => Task.FromResult(1L);
        public Task RotateGroupVersionAsync(string groupName, CancellationToken cancellationToken = default) => Task.CompletedTask;
        public Task SetWithSoftExpirationAsync<T>(string key, T value, TimeSpan softExpiration, TimeSpan hardExpiration, CancellationToken cancellationToken = default) => Task.CompletedTask;
        public Task<CacheResult<T>> GetWithMetadataAsync<T>(string key, CancellationToken cancellationToken = default) =>
            Task.FromResult(new CacheResult<T>(Value: default, IsStale: false, IsHit: false));
        public Task<T> GetOrSetWithSwrAsync<T>(string key, Func<Task<T>> factory, TimeSpan softExpiration, TimeSpan? hardExpiration = null, CancellationToken cancellationToken = default) => factory();
        public Task<TResponse> GetOrSetWithSwrAsync<TRequest, TResponse>(
            string key, TRequest request, Func<Task<TResponse>> factory,
            TimeSpan softExpiration, TimeSpan? hardExpiration = null,
            CancellationToken cancellationToken = default) where TRequest : class =>
            factory();
    }
}
