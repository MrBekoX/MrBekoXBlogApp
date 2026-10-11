using System.Threading.Channels;
using RabbitMQ.Client;
using RabbitMQ.Client.Events;

namespace BlogApp.BuildingBlocks.Messaging;

/// <summary>Tek bir mandatory yayının broker sonucu.</summary>
public sealed record BrokerPublishResult(bool Confirmed, bool Returned, string Detail);

/// <summary>basic.return ile geri dönen (routable olmayan) mesajın özeti; gövde teslim anında kopyalanır.</summary>
public sealed record ReturnedMessage(string Exchange, string RoutingKey, string ReplyText, byte[] Body);

/// <summary>
/// Confirm'lu ve mandatory broker yayıncısı (B2). Uzun ömürlü tek publisher kanalı
/// kullanır ([RMQ-DOTNET#C1]); her mesaj için bağlantı açılmaz.
///
/// - Publisher confirms broker kabulünü gösterir; işin tamamlanmasını değil (plan satır 16,
///   [RMQ-CONFIRMS#C1]). Sonuç <see cref="BrokerPublishResult"/> ile ayrı raporlanır.
/// - ``mandatory``: bağlanamayan routing key basic.return ile fark edilir ve başarı sayılmaz
///   (plan satır 261); return kaydı <see cref="ReadReturnedAsync"/> ile okunur.
/// - Önemli mesajlar persistent (delivery_mode=2) ve durable exchange'lere gider ([RMQ-RELIABILITY#C2]).
/// - AMQP properties zarf ile tutarlı set edilir: message_id, correlation_id,
///   content_type=application/json, type (B1 AgentAmqpProperties eşlemesi).
/// </summary>
public interface IAgentBrokerPublisher : IAsyncDisposable
{
    /// <summary>
    /// Gövdeyi persistent mesaj olarak yayınlar ve publisher confirm bekler.
    /// Routable olmayan mandatory mesaj confirmed=false, returned=true döner.
    /// </summary>
    Task<BrokerPublishResult> PublishAsync(
        string exchange,
        string routingKey,
        ReadOnlyMemory<byte> body,
        string? messageId = null,
        string? correlationId = null,
        string? type = null,
        CancellationToken cancellationToken = default);

    /// <summary>basic.return ile geri dönen son mesajı okur; timeout'ta null döner.</summary>
    Task<ReturnedMessage?> ReadReturnedAsync(TimeSpan timeout, CancellationToken cancellationToken = default);
}

public sealed class RabbitMqAgentPublisher : IAgentBrokerPublisher
{
    private readonly IRabbitMqConnectionManager _connections;
    private readonly RabbitMqSettings _settings;
    private readonly string[] _exchanges;
    private readonly SemaphoreSlim _publishGate = new(1, 1);
    private readonly Channel<ReturnedMessage> _returns = Channel.CreateBounded<ReturnedMessage>(64);
    private IChannel? _channel;

    /// <param name="exchanges">
    /// Yayınlama yetkisinin sahibi olunan exchange kümesi; pasif olarak alınır.
    /// Backend için commands+content, agent için events (K3 ve RabbitMQ 4.x pasif declare izin kuralı).
    /// </param>
    public RabbitMqAgentPublisher(IRabbitMqConnectionManager connections, RabbitMqSettings settings, string[] exchanges)
    {
        _connections = connections;
        _settings = settings;
        _exchanges = exchanges;
    }

    public async Task StartAsync(CancellationToken cancellationToken = default)
    {
        var connection = await _connections.GetConnectionAsync(cancellationToken);
        _channel = await connection.CreateChannelAsync(
            new CreateChannelOptions(
                publisherConfirmationsEnabled: true,
                publisherConfirmationTrackingEnabled: true),
            cancellationToken);

        foreach (var exchange in _exchanges)
        {
            await _channel.ExchangeDeclareAsync(
                exchange,
                ExchangeType.Topic,
                durable: true,
                autoDelete: false,
                passive: true,
                cancellationToken: cancellationToken);
        }

        _channel.BasicReturnAsync += OnBasicReturnAsync;
    }

    public async Task<BrokerPublishResult> PublishAsync(
        string exchange,
        string routingKey,
        ReadOnlyMemory<byte> body,
        string? messageId = null,
        string? correlationId = null,
        string? type = null,
        CancellationToken cancellationToken = default)
    {
        if (_channel is null)
        {
            throw new InvalidOperationException("RabbitMqAgentPublisher.StartAsync çağrılmadan yayın yapılmaz.");
        }

        if (body.Length > _settings.MaxPublishBytes)
        {
            throw new ArgumentException(
                $"gövde {body.Length} bayt; üst sınır {_settings.MaxPublishBytes} (B1 MaxPayloadBytes).",
                nameof(body));
        }

        var properties = new BasicProperties
        {
            DeliveryMode = DeliveryModes.Persistent,
            ContentType = "application/json",
            MessageId = messageId,
            CorrelationId = correlationId,
            Type = type,
        };

        // IChannel eşzamanlı yayına paylaşılmaz; confirm takipli yayınlar sıraya alınır.
        await _publishGate.WaitAsync(cancellationToken);
        try
        {
            await _channel.BasicPublishAsync(
                exchange,
                routingKey,
                mandatory: true,
                basicProperties: properties,
                body: body,
                cancellationToken: cancellationToken);
        }
        catch (Exception exception) when (exception is RabbitMQ.Client.Exceptions.PublishReturnException or RabbitMQ.Client.Exceptions.PublishException)
        {
            return new BrokerPublishResult(
                Confirmed: false,
                Returned: true,
                Detail: $"unroutable: {routingKey} -> {exchange}: {exception.Message}");
        }
        finally
        {
            _publishGate.Release();
        }

        return new BrokerPublishResult(Confirmed: true, Returned: false, Detail: string.Empty);
    }

    public async Task<ReturnedMessage?> ReadReturnedAsync(TimeSpan timeout, CancellationToken cancellationToken = default)
    {
        using var timeoutCts = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        timeoutCts.CancelAfter(timeout);
        try
        {
            return await _returns.Reader.ReadAsync(timeoutCts.Token);
        }
        catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested)
        {
            return null;
        }
    }

    private Task OnBasicReturnAsync(object sender, BasicReturnEventArgs @event)
    {
        // Callback bittikten sonra kullanılacak veri kopyalanır ([RMQ-DOTNET#C2] karşılığı).
        var body = @event.Body.ToArray();
        _returns.Writer.TryWrite(new ReturnedMessage(
            @event.Exchange,
            @event.RoutingKey,
            @event.ReplyText,
            body));
        return Task.CompletedTask;
    }

    public async ValueTask DisposeAsync()
    {
        if (_channel is not null)
        {
            _channel.BasicReturnAsync -= OnBasicReturnAsync;
            await _channel.CloseAsync();
            await _channel.DisposeAsync();
            _channel = null;
        }

        _returns.Writer.TryComplete();
        _publishGate.Dispose();
    }
}
