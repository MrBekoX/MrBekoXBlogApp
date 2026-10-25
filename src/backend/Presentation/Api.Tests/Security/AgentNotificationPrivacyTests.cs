using System.Text.Json;
using BlogApp.Core.Application.Common.Messaging;
using BlogApp.Presentation.Api.Hubs;
using BlogApp.Presentation.Api.Services;
using Microsoft.AspNetCore.SignalR;
using Microsoft.Extensions.Logging.Abstractions;
using Xunit;

namespace BlogApp.Presentation.Api.Tests.Security;

public sealed class AgentNotificationPrivacyTests
{
    [Fact]
    public async Task StaleGroupMembershipNeverReceivesProgressOrTerminalContent()
    {
        var clients = new CaptureClients();
        var notifier = new SignalRAgentRunNotifier(new CaptureHubContext(clients),
            NullLogger<SignalRAgentRunNotifier>.Instance);
        var runId = Guid.NewGuid().ToString("D");
        await notifier.NotifyAsync(new AgentRunNotification
        {
            RunId = runId,
            MessageId = Guid.NewGuid().ToString("D"),
            MessageType = "agent.run.completed",
            Status = "Completed",
            EventSequence = 3,
            OccurredAt = "2026-10-25T00:00:00Z",
            Message = "private-progress-sentinel",
            ResultJson = "{\"answer\":\"private-answer-sentinel\",\"profile\":\"private-profile-sentinel\"}",
        });
        Assert.Equal(AgentRunsHub.GroupFor(runId), clients.GroupName);
        Assert.Equal("RunUpdated", clients.Method);
        var body = JsonSerializer.SerializeToElement(Assert.Single(clients.Arguments!));
        Assert.Equal(runId, body.GetProperty("run_id").GetString());
        Assert.Equal(3, body.GetProperty("event_sequence").GetInt64());
        Assert.Equal(string.Empty, body.GetProperty("message").GetString());
        Assert.False(body.TryGetProperty("result", out _));
        Assert.DoesNotContain("private-", body.GetRawText());
    }

    private sealed class CaptureHubContext(CaptureClients clients) : IHubContext<AgentRunsHub>
    {
        public IHubClients Clients => clients;
        public IGroupManager Groups => throw new NotSupportedException();
    }

    private sealed class CaptureClients : IHubClients, IClientProxy
    {
        public string? GroupName { get; private set; }
        public string? Method { get; private set; }
        public object?[]? Arguments { get; private set; }
        public IClientProxy Group(string groupName) { GroupName = groupName; return this; }
        public Task SendCoreAsync(string method, object?[] args, CancellationToken cancellationToken = default)
        {
            Method = method;
            Arguments = args;
            return Task.CompletedTask;
        }
        public IClientProxy All => this;
        public IClientProxy AllExcept(IReadOnlyList<string> ids) => this;
        public IClientProxy Client(string id) => this;
        public IClientProxy Clients(IReadOnlyList<string> ids) => this;
        public IClientProxy GroupExcept(string name, IReadOnlyList<string> ids) => this;
        public IClientProxy Groups(IReadOnlyList<string> names) => this;
        public IClientProxy User(string id) => this;
        public IClientProxy Users(IReadOnlyList<string> ids) => this;
    }
}
