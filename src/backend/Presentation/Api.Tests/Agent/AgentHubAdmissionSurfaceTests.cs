using System.Net;
using System.Net.WebSockets;
using System.Security.Claims;
using System.IdentityModel.Tokens.Jwt;
using System.Text;
using System.Text.Json;
using BlogApp.Core.Application.Common.Interfaces.Data;
using BlogApp.Core.Application.Common.Interfaces.Services;
using BlogApp.Core.Application.Common.Messaging;
using BlogApp.Core.Application.Features.AgentFeature.Services;
using BlogApp.Core.Domain.Entities;
using BlogApp.Core.Domain.Enums;
using BlogApp.Infrastructure.Messaging;
using BlogApp.Infrastructure.Persistence;
using BlogApp.Infrastructure.Persistence.Repositories;
using BlogApp.Presentation.Api.Extensions;
using BlogApp.Presentation.Api.Hubs;
using BlogApp.Presentation.Api.Middlewares;
using BlogApp.Presentation.Api.Security;
using BlogApp.Presentation.Api.Services;
using BlogApp.Presentation.Api.Tests.Security;
using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.TestHost;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging.Abstractions;
using Xunit;

namespace BlogApp.Presentation.Api.Tests.Agent;

[Collection("agent-b10")]
public sealed class AgentHubAdmissionSurfaceTests(AgentB10DatabaseFixture fixture) : IAsyncLifetime
{
    public Task InitializeAsync() => fixture.ResetAsync();
    public Task DisposeAsync() => Task.CompletedTask;

    [Fact]
    public async Task ActualWebSocketFramesCannotResetOwnerAndIpQuotaByUsingAnotherConnection()
    {
        var owner = Guid.NewGuid();
        Guid runId;
        await using (var context = fixture.CreateContext())
            runId = (await AgentB10TestHost.SeedRunAsync(context, ownerKey: $"u:{owner:D}")).Id;
        await using var app = BuildHost(owner);
        await app.StartAsync();
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(20));
        var client = app.GetTestServer().CreateWebSocketClient();
        using var first = await client.ConnectAsync(new Uri("ws://localhost" + AgentRunsHub.HubPath), timeout.Token);
        using var second = await client.ConnectAsync(new Uri("ws://localhost" + AgentRunsHub.HubPath), timeout.Token);
        var firstFrames = new Frames(first, timeout.Token);
        var secondFrames = new Frames(second, timeout.Token);
        await firstFrames.Handshake(); await secondFrames.Handshake();
        Assert.Null(await firstFrames.Subscribe("1", runId));
        Assert.Null(await secondFrames.Subscribe("2", runId));
        Assert.Equal(2, app.Services.GetRequiredService<SignalRAdmissionControl>().ActiveHubConnectionCount);
        var error = await firstFrames.Subscribe("3", runId);
        Assert.Contains("invocation limit", error);
    }

    [Theory]
    [InlineData("published", "generation_delta")]
    [InlineData("draft", "generation_delta")]
    [InlineData("deleted", "generation_delta")]
    [InlineData("published", "retrieval_completed")]
    [InlineData("draft", "retrieval_completed")]
    public async Task ActualProjectedSignalRFrameHonorsCurrentArticlePublication(string state, string kind)
    {
        var owner = Guid.NewGuid();
        Guid runId;
        Guid conversationId;
        Guid articleId;
        await using (var context = fixture.CreateContext())
        {
            var author = new User { UserName = "signalr-" + Guid.NewGuid().ToString("N"),
                Email = Guid.NewGuid().ToString("N") + "@example.com", PasswordHash = "test-only" };
            context.Users.Add(author); await context.SaveChangesAsync();
            var article = new BlogPost { Title = "Publication boundary", Slug = Guid.NewGuid().ToString("N"),
                Content = "approved source text", AuthorId = author.Id };
            article.Publish(); context.Posts.Add(article); await context.SaveChangesAsync();
            articleId = article.Id;
            var run = await AgentB10TestHost.SeedRunAsync(context, ownerKey: $"u:{owner:D}", articleId: articleId);
            runId = run.Id; conversationId = run.ConversationId;
        }
        await using var app = BuildHost(owner);
        await app.StartAsync();
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(20));
        using var socket = await app.GetTestServer().CreateWebSocketClient()
            .ConnectAsync(new Uri("ws://localhost" + AgentRunsHub.HubPath), timeout.Token);
        var frames = new Frames(socket, timeout.Token);
        await frames.Handshake();
        Assert.Null(await frames.Subscribe("1", runId));
        // Withdrawal happens after subscription, so ownership cannot substitute
        // for a current publication check on the outbound body.
        await using var projection = fixture.CreateContext();
        if (state != "published")
            await projection.Posts.Where(post => post.Id == articleId).ExecuteUpdateAsync(update => update
                .SetProperty(post => post.Status, PostStatus.Draft).SetProperty(post => post.IsDeleted, state == "deleted"));
        const string body = "approved answer text from source";
        var payload = JsonSerializer.SerializeToElement(new { event_sequence = 1, kind, message = body });
        var envelope = new AgentEnvelope { MessageId = Guid.NewGuid().ToString("D"), MessageType = AgentMessageTypes.RunProgressed,
            SchemaVersion = 1, RunId = runId.ToString("D"), ConversationId = conversationId.ToString("D"),
            CorrelationId = Guid.NewGuid().ToString("D"), OccurredAt = AgentCommandEnvelopeComposer.FormatUtc(DateTimeOffset.UtcNow),
            Producer = "agent-py", Payload = payload };
        var handler = new AgentRunEventProjectionHandler(new UnitOfWork(projection), projection,
            new EfAgentCollaborationStore(projection), new AgentResultPresentationGuard(projection),
            NullLogger<AgentRunEventProjectionHandler>.Instance);
        var result = await handler.ApplyAsync(new AgentRunEventProjectionEvent(
            AgentRunEventProjectionHandler.ConsumerName, envelope, payload.GetRawText(), 1, false,
            ProgressMessage: body, ProgressKind: kind));
        Assert.Equal(AgentEventDecision.Apply, result.Decision);
        Assert.NotNull(result.Notification);
        await app.Services.GetRequiredService<IAgentRunNotifier>().NotifyAsync(result.Notification!, timeout.Token);
        var notice = await frames.Notification();
        Assert.Equal(runId.ToString("D"), notice.GetProperty("run_id").GetString());
        Assert.Equal(1, notice.GetProperty("event_sequence").GetInt64());
        Assert.Equal(state == "published" ? body : string.Empty, result.Notification!.Message);
        Assert.Equal(string.Empty, notice.GetProperty("message").GetString());
        Assert.DoesNotContain(body, notice.GetRawText());
        Assert.Equal(1, await projection.AgentEventInboxes.CountAsync(inbox => inbox.RunId == runId && inbox.Status == "applied"));
    }

    [Fact]
    public async Task RevokedSubscriberGetsOnlyMetadataAndCannotSubscribeAgain()
    {
        var owner = Guid.NewGuid();
        Guid runId;
        await using (var context = fixture.CreateContext())
            runId = (await AgentB10TestHost.SeedRunAsync(context, ownerKey: $"u:{owner:D}")).Id;
        var blacklist = new MutableTokenBlacklist();
        await using var app = BuildHost(owner, blacklist, realJwt: true);
        await app.StartAsync();
        var token = AgentCredentialLifetimeTests.Generate(owner);
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(15));
        var client = app.GetTestServer().CreateWebSocketClient();
        client.ConfigureRequest = request => request.Headers["Authorization"] = "Bearer " + token;
        using var socket = await client.ConnectAsync(new Uri("ws://localhost" + AgentRunsHub.HubPath), timeout.Token);
        var frames = new Frames(socket, timeout.Token);
        await frames.Handshake();
        Assert.Null(await frames.Subscribe("1", runId));
        var jti = new JwtSecurityTokenHandler().ReadJwtToken(token).Id;
        await blacklist.BlacklistTokenAsync(jti, TimeSpan.FromMinutes(5));
        await app.Services.GetRequiredService<IAgentRunNotifier>().NotifyAsync(new AgentRunNotification
        {
            RunId = runId.ToString("D"), MessageId = Guid.NewGuid().ToString("D"),
            MessageType = "agent.run.completed", Status = "Completed", EventSequence = 3,
            OccurredAt = "2026-10-25T00:00:00Z", Message = "private-progress-sentinel",
            ResultJson = "{\"answer\":\"private-answer-sentinel\"}",
        });
        var notice = await frames.Notification();
        Assert.DoesNotContain("private-", notice.GetRawText());
        Assert.False(notice.TryGetProperty("result", out _));
        Assert.NotNull(await frames.Subscribe("2", runId));
    }

    [Fact]
    public async Task GuestSubscriptionRemainsAvailableWithoutAnAuthenticationToken()
    {
        var guest = Guid.NewGuid().ToString("D");
        Guid runId;
        await using (var context = fixture.CreateContext())
            runId = (await AgentB10TestHost.SeedRunAsync(context, ownerKey: "g:" + guest)).Id;
        await using var app = BuildHost(Guid.NewGuid(), realJwt: true);
        await app.StartAsync();
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(15));
        var client = app.GetTestServer().CreateWebSocketClient();
        client.ConfigureRequest = request => request.Headers["Cookie"] = AgentGuestSessionService.CookieName + "=" + guest;
        using var socket = await client.ConnectAsync(new Uri("ws://localhost" + AgentRunsHub.HubPath), timeout.Token);
        var frames = new Frames(socket, timeout.Token);
        await frames.Handshake();
        Assert.Null(await frames.Subscribe("1", runId));
    }

    private WebApplication BuildHost(Guid owner, MutableTokenBlacklist? blacklist = null, bool realJwt = false)
    {
        var builder = WebApplication.CreateBuilder();
        builder.WebHost.UseTestServer();
        builder.Services.AddDbContext<AppDbContext>(options => options.UseNpgsql(fixture.TestConnectionString));
        builder.Services.AddScoped<IApplicationDbContext>(provider => provider.GetRequiredService<AppDbContext>());
        builder.Services.AddAgentSignalRAdmission(new ConfigurationBuilder().AddInMemoryCollection(
            new Dictionary<string, string?> { ["SignalRRateLimit:MaxInvocationsPerMinute"] = "2" }).Build());
        builder.Services.AddSingleton<IAgentRunNotifier, SignalRAgentRunNotifier>();
        builder.Services.AddSingleton<ITokenBlacklistService>(blacklist ?? new MutableTokenBlacklist());
        builder.Services.AddJwtAuthentication(AgentCredentialLifetimeTests.Configuration());
        var app = builder.Build();
        app.UseWebSockets();
        app.UseAuthentication();
        app.UseAuthorization();
        app.Use((context, next) =>
        {
            if (!realJwt)
                context.User = new ClaimsPrincipal(new ClaimsIdentity(
                    new JwtSecurityTokenHandler().ReadJwtToken(AgentCredentialLifetimeTests.Generate(owner)).Claims, "test"));
            context.Connection.RemoteIpAddress = IPAddress.Parse("203.0.113.20");
            return next(context);
        });
        app.UseMiddleware<SignalRConnectionLimitMiddleware>();
        app.MapAgentRunsHub();
        return app;
    }

    private sealed class Frames(WebSocket socket, CancellationToken cancellation)
    {
        private string _pending = string.Empty;
        public async Task Handshake()
        {
            await Send("{\"protocol\":\"json\",\"version\":1}");
            using var json = JsonDocument.Parse(await Receive());
            Assert.False(json.RootElement.TryGetProperty("error", out _));
        }
        public async Task<string?> Subscribe(string id, Guid runId)
        {
            await Send(JsonSerializer.Serialize(new { type = 1, invocationId = id, target = "SubscribeToRun", arguments = new[] { runId.ToString("D") } }));
            while (true)
            {
                using var json = JsonDocument.Parse(await Receive());
                var root = json.RootElement;
                if (root.TryGetProperty("type", out var type) && type.GetInt32() == 3
                    && root.GetProperty("invocationId").GetString() == id)
                    return root.TryGetProperty("error", out var error) ? error.GetString() : null;
            }
        }
        public async Task<JsonElement> Notification()
        {
            while (true)
            {
                using var json = JsonDocument.Parse(await Receive());
                var root = json.RootElement;
                if (root.TryGetProperty("type", out var type) && type.GetInt32() == 1
                    && root.GetProperty("target").GetString() == "RunUpdated")
                    return root.GetProperty("arguments")[0].Clone();
            }
        }
        private Task Send(string json) => socket.SendAsync(new ArraySegment<byte>(Encoding.UTF8.GetBytes(json + "\u001e")),
            WebSocketMessageType.Text, true, cancellation);
        private async Task<string> Receive()
        {
            var buffer = new byte[4096];
            while (true)
            {
                var separator = _pending.IndexOf('\u001e');
                if (separator >= 0)
                {
                    var frame = _pending[..separator]; _pending = _pending[(separator + 1)..]; return frame;
                }
                var result = await socket.ReceiveAsync(buffer, cancellation);
                if (result.MessageType == WebSocketMessageType.Close) throw new InvalidOperationException("Unexpected websocket close");
                _pending += Encoding.UTF8.GetString(buffer, 0, result.Count);
            }
        }
    }
}
