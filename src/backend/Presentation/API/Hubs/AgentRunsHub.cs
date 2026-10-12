using Microsoft.AspNetCore.SignalR;

namespace BlogApp.Presentation.Api.Hubs;

/// <summary>
/// Agent run canlı bildirim hub'ı (B5, plan: "Commit edilmiş projection üzerinden UI
/// bildirimi üret" + "Bağlantısı kopmuş tarayıcının kaybettiği bildirimi kalıcı
/// GET/replay yolu tamamlar" — replay uç noktaları B10'dadır).
///
/// Bu hub yalnız ince yayın katmanıdır: durum TUTMAZ ([SIGNALR-HUBS#C1]: hub örneği
/// üzerinde kalıcı iş state'i tutmaya güvenilmez); bildirim, projection commit'inden
/// sonra IAgentRunNotifier → IHubContext üzerinden gönderilir ([SIGNALR-HUBS#C2]).
/// Grup adı ``run:{run_id}``'dir; run_id kanonik UUID doğrulamasından geçmeden
/// grup üyeliği verilmez. Bildirim "okundu" garantisi taşımaz: tarayıcı kopması
/// sırasındaki olaylar commit edilmiş projection'dan (B10 replay) tamamlanır.
/// </summary>
public sealed class AgentRunsHub(ILogger<AgentRunsHub> logger) : Hub
{
    public const string HubPath = "/hubs/agent-runs";

    public static string GroupFor(string runId) => $"run:{runId}";

    public async Task SubscribeToRun(string runId)
    {
        if (!Guid.TryParseExact(runId, "D", out _))
        {
            throw new HubException("run_id kanonik UUID olmalıdır.");
        }

        await Groups.AddToGroupAsync(Context.ConnectionId, GroupFor(runId));
        logger.LogDebug("Client {ConnectionId} subscribed to {Group}", Context.ConnectionId, GroupFor(runId));
    }

    public async Task UnsubscribeFromRun(string runId)
    {
        if (!Guid.TryParseExact(runId, "D", out _))
        {
            throw new HubException("run_id kanonik UUID olmalıdır.");
        }

        await Groups.RemoveFromGroupAsync(Context.ConnectionId, GroupFor(runId));
        logger.LogDebug("Client {ConnectionId} unsubscribed from {Group}", Context.ConnectionId, GroupFor(runId));
    }
}
