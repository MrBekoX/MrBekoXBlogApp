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

    public async Task StartAsync(CancellationToken cancellationToken = default)
    {
        var connection = await _connections.GetConnectionAsync(cancellationToken);
        _channel = await connection.CreateChannelAsync(cancellationToken: cancellationToken);
        await _channel.BasicQosAsync(0, (ushort)Math.Clamp(_settings.ConsumerPrefetchCount, 1, ushort.MaxValue), false, cancellationToken);

        _consumer = new AsyncEventingBasicConsumer(_channel);
        _consumer.ReceivedAsync += OnReceivedAsync;
        await _channel.BasicConsumeAsync(_queueName, autoAck: false, _consumer, cancellationToken);
    }

    public async Task StopAsync(CancellationToken cancellationToken = default)
    {
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
        if (_channel is null)
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
            await _channel.BasicNackAsync(@event.DeliveryTag, multiple: false, requeue: false);
            return;
        }

        try
        {
            await HandleAsync(@event.Exchange, @event.RoutingKey, body, @event, CancellationToken.None);
            await _channel.BasicAckAsync(@event.DeliveryTag, multiple: false);
        }
        catch (Exception)
        {
            // requeue yok: kuyruğun x-dead-letter-exchange hedefine düşer, döngü kurulmaz.
            await _channel.BasicNackAsync(@event.DeliveryTag, multiple: false, requeue: false);
        }
    }

    public async ValueTask DisposeAsync()
    {
        await StopAsync();
    }
}
