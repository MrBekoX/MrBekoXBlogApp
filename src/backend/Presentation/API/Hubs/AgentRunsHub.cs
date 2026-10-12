using BlogApp.Core.Application.Common.Interfaces.Data;
using BlogApp.Presentation.Api.Services;
using Microsoft.AspNetCore.SignalR;
using Microsoft.EntityFrameworkCore;

namespace BlogApp.Presentation.Api.Hubs;

/// <summary>
/// Agent run canlı bildirim hub'ı (B5, plan: "Commit edilmiş projection üzerinden UI
/// bildirimi üret" + "Bağlantısı kopmuş tarayıcının kaybettiği bildirimi kalıcı
/// GET/replay yolu tamamlanır" — replay uç noktaları B10'dadır).
///
/// Bu hub yalnız ince yayın katmanıdır: durum TUTMAZ ([SIGNALR-HUBS#C1]: hub örneği
/// üzerinde kalıcı iş state'i tutmaya güvenilmez); bildirim, projection commit'inden
/// sonra IAgentRunNotifier → IHubContext üzerinden gönderilir ([SIGNALR-HUBS#C2]).
/// Grup adı ``run:{run_id}``'dir; run_id kanonik UUID doğrulamasından ve (B10) RUN
/// SAHİPLİĞİ denetiminden geçmeden grup üyeliği verilmez — terminal bildirimi sonuç
/// snapshot'ı taşıyabildiğinden yabancı bir bağlantının gruba girmesi engellenir
/// (plan B10 kabul ölçütü: başka kullanıcının run'ına erişim engeli). Sahiplik
/// backend AgentRun kaydı üzerinden doğrulanır: JWT kimliği ya da sunucu tarafı
/// misafir oturum çerezi; istemcinin gönderdiği owner alanı yetki kaynağı değildir.
/// </summary>
public sealed class AgentRunsHub(
    IApplicationDbContext dbContext,
    ILogger<AgentRunsHub> logger) : Hub
{
    public const string HubPath = "/hubs/agent-runs";

    public static string GroupFor(string runId) => $"run:{runId}";

    public async Task SubscribeToRun(string runId)
    {
        if (!Guid.TryParseExact(runId, "D", out var parsedRunId))
        {
            throw new HubException("run_id kanonik UUID olmalıdır.");
        }

        if (!await CallerOwnsRunAsync(parsedRunId, Context.ConnectionAborted))
        {
            logger.LogWarning(
                "[AgentRunsHub] yabancı/kimliksiz bağlantı run grubuna alınmadı: {ConnectionId} run {RunId}",
                Context.ConnectionId, parsedRunId);
            throw new HubException("Bu agent işine erişim yetkiniz yok.");
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

    /// <summary>Bağlantı sahibi bu run'ın sahibi mi? Kimlik: hub bağlantı kullanıcısı
    /// (negotiate'te çözülen JWT) veya sunucu tarafı misafir çerezi (K5).</summary>
    private async Task<bool> CallerOwnsRunAsync(Guid runId, CancellationToken cancellationToken)
    {
        Guid? userId = null;
        var userIdClaim = Context.User?.FindFirst("userId") ?? Context.User?.FindFirst(System.Security.Claims.ClaimTypes.NameIdentifier);
        if (userIdClaim is not null && Guid.TryParse(userIdClaim.Value, out var parsedUser))
        {
            userId = parsedUser;
        }

        var guestSessionId = Context.GetHttpContext()?.Request.Cookies[AgentGuestSessionService.CookieName];

        if (userId is null && string.IsNullOrWhiteSpace(guestSessionId))
        {
            return false;
        }

        var ownerKey = userId is not null ? $"u:{userId.Value:D}" : $"g:{guestSessionId!.Trim()}";
        return await dbContext.AgentRuns
            .AsNoTracking()
            .AnyAsync(r => r.Id == runId && r.OwnerKey == ownerKey, cancellationToken);
    }
}
