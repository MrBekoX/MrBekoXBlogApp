using RabbitMQ.Client;
using RabbitMQ.Client.Events;

namespace BlogApp.BuildingBlocks.Messaging;

/// <summary>
/// Uzun ömürlü RabbitMQ consumer tabanı (B2): sınırlı prefetch, manuel ACK, DLX'e nack.
///
/// - Manuel ACK + sınırlı prefetch ile açık teslim sayısı kontrol edilir ([RMQ-CONFIRMS#C2]);
///   ACK, işleme tamamlandıktan sonra teslimin geldiği kanal üzerinden verilir.
///   Plan: Python ACK'i kalıcı sorumluluk devrinden sonra verir; bu taban B3/B4 tüketici
///   hizmetleri için aynı sırayı uygular (önce işle, sonra ACK).
/// - Handler istisnası mesajı ``BasicNackAsync(requeue: false)`` ile kuyruğun DLX hedefine
///   gönderir; sürekli requeue döngüsü kurulmaz (plan B7 kuralının B2 tabanı).
/// - Client 7.x'te gövde ReadOnlyMemory olarak gelir; callback bittikten sonra kullanılacak
///   veri callback içinde <see cref="RabbitMQ.Client.Events.BasicDeliverEventArgs.Body.ToArray"/>
///   ile kopyalanır ([RMQ-DOTNET#C2]).
/// - Consumer gövdesi bağlantı recovery'sinde istemci tarafından yeniden kaydedilir
///   (TopologyRecoveryEnabled); shutdown'da kanal kapatılarak tüketim nazikçe durdurulur.
/// </summary>
public interface IAgentBrokerConsumer : IAsyncDisposable
{
    Task StartAsync(CancellationToken cancellationToken = default);

    Task StopAsync(CancellationToken cancellationToken = default);
}

public abstract class RabbitMqAgentConsumer : IAgentBrokerConsumer
{
    private readonly IRabbitMqConnectionManager _connections;
    private readonly RabbitMqSettings _settings;
    private readonly string _queueName;
    private IChannel? _channel;
    private AsyncEventingBasicConsumer? _consumer;
    private CancellationTokenSource _stopping = new();

    protected RabbitMqAgentConsumer(IRabbitMqConnectionManager connections, RabbitMqSettings settings, string queueName)
    {
        _connections = connections;
        _settings = settings;
        _queueName = queueName;
    }

    /// <summary>Teslim edilen tek mesajı işler; istisna mesajı DLX'e yönlendirir.</summary>
    protected abstract Task HandleAsync(
        string exchange,
        string routingKey,
        byte[] body,
        BasicDeliverEventArgs delivery,
        CancellationToken cancellationToken);

    protected virtual bool IsRetryable(Exception error) => false;
    protected virtual IReadOnlyList<TimeSpan> RetryDelays => [];

    public async Task StartAsync(CancellationToken cancellationToken = default)
    {
        if (_stopping.IsCancellationRequested)
        {
            _stopping.Dispose();
            _stopping = new CancellationTokenSource();
        }
        var connection = await _connections.GetConnectionAsync(cancellationToken);
        _channel = await connection.CreateChannelAsync(cancellationToken: cancellationToken);
        await _channel.BasicQosAsync(0, (ushort)Math.Clamp(_settings.ConsumerPrefetchCount, 1, ushort.MaxValue), false, cancellationToken);

        _consumer = new AsyncEventingBasicConsumer(_channel);
        _consumer.ReceivedAsync += OnReceivedAsync;
        await _channel.BasicConsumeAsync(_queueName, autoAck: false, _consumer, cancellationToken);
    }

    public async Task StopAsync(CancellationToken cancellationToken = default)
    {
        await _stopping.CancelAsync();
        if (_channel is not null)
        {
            await _channel.CloseAsync(cancellationToken);
            await _channel.DisposeAsync();
            _channel = null;
            _consumer = null;
        }
    }

    private async Task OnReceivedAsync(object sender, BasicDeliverEventArgs @event)
    {
        var channel = _channel;
        var stoppingToken = _stopping.Token;
        if (channel is null || stoppingToken.IsCancellationRequested)
        {
            return;
        }

        byte[] body;
        try
        {
            // ReadOnlyMemory teslim ömrü callback ile sınırlıdır; ACK sonrası kullanılacak
            // veri burada kopyalanır ([RMQ-DOTNET#C2]).
            body = @event.Body.ToArray();
        }
        catch (Exception)
        {
            await channel.BasicNackAsync(@event.DeliveryTag, multiple: false, requeue: false);
            return;
        }

        try
        {
            await ConsumerDeliveryRetry.ExecuteAsync(
                ct => HandleAsync(@event.Exchange, @event.RoutingKey, body, @event, ct),
                IsRetryable, RetryDelays, stoppingToken);
            await channel.BasicAckAsync(@event.DeliveryTag, multiple: false);
        }
        catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested)
        {
            // Closing the channel returns the still-unacknowledged delivery to
            // the broker. Shutdown is not a permanent processing failure.
        }
        catch (Exception)
        {
            // requeue yok: kuyruğun x-dead-letter-exchange hedefine düşer, döngü kurulmaz.
            await channel.BasicNackAsync(@event.DeliveryTag, multiple: false, requeue: false);
        }
    }

    public async ValueTask DisposeAsync()
    {
        await StopAsync();
    }
}
