using BlogApp.BuildingBlocks.Messaging;
using BlogApp.Core.Application.Common.Interfaces.Messaging;
using BlogApp.Core.Application.Common.Options;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;

namespace BlogApp.Infrastructure.Messaging;

/// <summary>
/// Süreli hazırlık önbelleği (K4: 30 sn). Sonuç — hata dahil — süre boyunca tekrar kullanılır;
/// probe hatası "hazır değil"dir (fail-closed) ve broker'a sürekli yük bindirmez. Eşzamanlı
/// çağrılar tek probe'u bekler.
/// </summary>
public sealed class AgentReadinessCache(TimeSpan timeToLive, TimeProvider timeProvider)
{
    private readonly SemaphoreSlim _gate = new(1, 1);
    private (bool Ready, DateTimeOffset CheckedAt)? _last;

    public async Task<bool> GetAsync(Func<CancellationToken, Task<bool>> probe, CancellationToken cancellationToken = default)
    {
        if (TryGetFresh(out var cached))
        {
            return cached;
        }

        await _gate.WaitAsync(cancellationToken);
        try
        {
            if (TryGetFresh(out cached))
            {
                return cached;
            }

            bool ready;
            try
            {
                ready = await probe(cancellationToken);
            }
            catch (Exception exception) when (exception is not OperationCanceledException)
            {
                ready = false;
            }

            _last = (ready, timeProvider.GetUtcNow());
            return ready;
        }
        finally
        {
            _gate.Release();
        }
    }

    private bool TryGetFresh(out bool ready)
    {
        if (_last is { } last && timeProvider.GetUtcNow() - last.CheckedAt < timeToLive)
        {
            ready = last.Ready;
            return true;
        }

        ready = false;
        return false;
    }
}

/// <summary>
/// v2 üretici bariyerinin RabbitMQ uygulaması (K4): <see cref="AgentMessagingTopology.ExecuteQueueV2"/>
/// ve <see cref="AgentMessagingTopology.ControlQueueV2"/> kuyrukları pasif bildirilir (topolojiyi
/// değiştirmez); ikisi de varsa ve her birinde en az bir tüketici (yeni worker) varsa hazırdır.
/// Var olmayan kuyruğun pasif bildirimi kanalı kapatır; her probe kendi kısa ömürlü kanalını açar.
/// Broker bağlantı hatası, kuyruk yokluğu veya tüketicisiz kuyruk → hazır değil.
/// </summary>
public sealed class RabbitMqAgentWireV2Readiness : IAgentWireV2Readiness
{
    private static readonly string[] RequiredQueues =
        [AgentMessagingTopology.ExecuteQueueV2, AgentMessagingTopology.ControlQueueV2];

    private readonly IRabbitMqConnectionManager _connections;
    private readonly ILogger<RabbitMqAgentWireV2Readiness> _logger;
    private readonly AgentReadinessCache _cache;

    public RabbitMqAgentWireV2Readiness(
        IRabbitMqConnectionManager connections,
        IOptions<AgentWireV2Settings> options,
        ILogger<RabbitMqAgentWireV2Readiness> logger,
        TimeProvider? timeProvider = null)
    {
        _connections = connections;
        _logger = logger;
        _cache = new AgentReadinessCache(
            TimeSpan.FromSeconds(Math.Max(1, options.Value.ReadinessCacheSeconds)),
            timeProvider ?? TimeProvider.System);
    }

    public Task<bool> IsReadyAsync(CancellationToken cancellationToken = default) =>
        _cache.GetAsync(ProbeAsync, cancellationToken);

    private async Task<bool> ProbeAsync(CancellationToken cancellationToken)
    {
        try
        {
            var connection = await _connections.GetConnectionAsync(cancellationToken);
            foreach (var queue in RequiredQueues)
            {
                await using var channel = await connection.CreateChannelAsync(cancellationToken: cancellationToken);
                var declared = await channel.QueueDeclarePassiveAsync(queue, cancellationToken);
                if (declared.ConsumerCount < 1)
                {
                    _logger.LogInformation(
                        "[AgentWireV2] v2 bariyeri kapalı: {Queue} kuyruğunda tüketici yok", queue);
                    return false;
                }
            }

            return true;
        }
        catch (Exception exception) when (exception is not OperationCanceledException)
        {
            _logger.LogWarning(
                "[AgentWireV2] v2 bariyeri kapalı: kuyruk hazırlığı doğrulanamadı ({Message})", exception.Message);
            return false;
        }
    }
}
