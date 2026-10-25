using BlogApp.Core.Application.Common.Messaging;
using BlogApp.Presentation.Api.Hubs;
using Microsoft.AspNetCore.SignalR;

namespace BlogApp.Presentation.Api.Services;

/// <summary>
/// Projection commit'i sonrası SignalR yayını (B5). <see cref="AgentRunsHub"/>
/// grubuna ``RunUpdated`` olayı gönderir; payload contract tabanlı snake_case
/// alanlarla yayınlanır. Yayın hatasını yutmaz: best-effort kararı tüketici
/// (Infrastructure consumer) uygular; bu sınıf yalnız hub kanalına gönderir.
/// </summary>
public sealed class SignalRAgentRunNotifier(
    IHubContext<AgentRunsHub> hubContext,
    ILogger<SignalRAgentRunNotifier> logger) : IAgentRunNotifier
{
    public async Task NotifyAsync(AgentRunNotification notification, CancellationToken cancellationToken = default)
    {
        var payload = new Dictionary<string, object?>
        {
            ["run_id"] = notification.RunId,
            ["message_id"] = notification.MessageId,
            ["message_type"] = notification.MessageType,
            ["status"] = notification.Status,
            ["event_sequence"] = notification.EventSequence,
            // Connections cache credentials and groups. Only a fresh authorized
            // GET/replay may release content after revocation or source changes.
            ["message"] = string.Empty,
            ["occurred_at"] = notification.OccurredAt,
        };
        var group = AgentRunsHub.GroupFor(notification.RunId);
        await hubContext.Clients.Group(group).SendAsync("RunUpdated", payload, cancellationToken);
        logger.LogDebug(
            "[AgentRunsHub] bildirim yayınlandı: group {Group} type {Type} seq {Seq}",
            group, notification.MessageType, notification.EventSequence);
    }
}
