using System.Text;
using System.Text.Json;
using BlogApp.BuildingBlocks.Messaging;
using BlogApp.Core.Application.Common.Messaging;
using BlogApp.Core.Application.Common.Options;
using BlogApp.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;

namespace BlogApp.Infrastructure.Messaging;

/// <summary>
/// Transactional outbox relay (plan satır 295-303): bekleyen kayıtları lease/claim ile alır
/// (FOR UPDATE SKIP LOCKED — iki publisher aynı kaydı alamaz), B2 confirm'lu publisher'ı ile
/// persistent yayınlar, confirm sonrası kaydı tamamlar. Confirm zaman aşımı veya broker
/// bağlantı hatasında kayıt beklemede kalır; lease dolunca AYNI message_id ile tekrar
/// yayınlanır (consumer tarafı inbox tekilleştirmesi B4'tedir). Broker kapalıysa döngü
/// çökmez; kayıtlar DB'de kalır (kabul ölçütü: DB commit sonrası broker kapansa iş kaybolmaz).
/// </summary>
public sealed class OutboxRelayService(
    IServiceScopeFactory scopeFactory,
    RabbitMqAgentPublisher publisher,
    IOptions<AgentOutboxRelaySettings> relayOptions,
    ILogger<OutboxRelayService> logger) : BackgroundService
{
    private readonly SemaphoreSlim _startGate = new(1, 1);
    private bool _publisherReady;

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        logger.LogInformation("Outbox relay başladı (batch {Batch}, poll {Poll}s)",
            relayOptions.Value.BatchSize, relayOptions.Value.PollIntervalSeconds);

        using var timer = new PeriodicTimer(TimeSpan.FromSeconds(Math.Max(relayOptions.Value.PollIntervalSeconds, 1)));
        while (!stoppingToken.IsCancellationRequested)
        {
            try
            {
                await RelayBatchAsync(stoppingToken);
            }
            catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested)
            {
                break;
            }
            catch (Exception exception)
            {
                // Döngü çökmez; kayıtlar DB'de beklemeye döner (kabul ölçütü).
                logger.LogError(exception, "Outbox relay döngüsünde beklenmeyen hata");
            }

            try
            {
                await timer.WaitForNextTickAsync(stoppingToken);
            }
            catch (OperationCanceledException)
            {
                break;
            }
        }

        logger.LogInformation("Outbox relay durdu");
    }

    private async Task RelayBatchAsync(CancellationToken cancellationToken)
    {
        if (!await EnsurePublisherReadyAsync(cancellationToken))
        {
            return; // broker kapalı: kayıt beklemede kalır, bir sonraki döngüde denenir
        }

        var relay = relayOptions.Value;
        await using var scope = scopeFactory.CreateAsyncScope();
        var context = scope.ServiceProvider.GetRequiredService<AppDbContext>();
        var store = new OutboxClaimStore(context);

        var claimed = await store.ClaimBatchAsync(
            relay.InstanceName,
            relay.BatchSize,
            LeaseFor(relay, attempt: 1),
            cancellationToken);
        if (claimed.Count == 0)
        {
            return;
        }

        OutboxMetrics.Claimed.Add(claimed.Count);
        foreach (var record in claimed)
        {
            cancellationToken.ThrowIfCancellationRequested();
            await PublishRecordAsync(store, record, relay, cancellationToken);
        }
    }

    private async Task PublishRecordAsync(
        OutboxClaimStore store,
        OutboxClaimedRecord record,
        AgentOutboxRelaySettings relay,
        CancellationToken cancellationToken)
    {
        AgentEnvelope? envelope;
        try
        {
            envelope = JsonSerializer.Deserialize<AgentEnvelope>(record.EnvelopeJson, AgentCommandEnvelopeComposer.SerializerOptions);
        }
        catch (JsonException)
        {
            envelope = null;
        }

        if (envelope is null || envelope.MessageId != record.MessageId)
        {
            // Bozuk kayıt yayınlanamaz; sonsuz deneme üretmesin diye üst denemeye zorlanır.
            logger.LogError("Outbox kaydı {Id} zarf çözümlemesi başarısız (message_id {MessageId})",
                record.Id, record.MessageId);
            await store.MarkAttemptFailedAsync(record.Id, "envelope_json bozuk", LeaseFor(relay, 1), 1, cancellationToken);
            OutboxMetrics.PublishFailed.Add(1);
            return;
        }

        // Transport tekrar sayacı güncellenir; message_id dahil diğer alanlar korunur (satır 301).
        var payloadJson = AgentCommandEnvelopeComposer.WithDeliveryAttempt(record.EnvelopeJson, record.AttemptCount - 1);
        var body = Encoding.UTF8.GetBytes(payloadJson);
        var nextLease = LeaseFor(relay, record.AttemptCount);

        try
        {
            var result = await publisher
                .PublishAsync(record.Exchange, record.RoutingKey, body, envelope.MessageId, envelope.CorrelationId,
                    envelope.MessageType, cancellationToken)
                .WaitAsync(TimeSpan.FromSeconds(Math.Max(relay.ConfirmTimeoutSeconds, 1)), cancellationToken);

            if (result.Confirmed)
            {
                if (await store.MarkPublishedAsync(record.Id, DateTime.UtcNow, cancellationToken))
                {
                    OutboxMetrics.Published.Add(1);
                    OutboxMetrics.AgeSeconds.Record((DateTimeOffset.UtcNow - record.CreatedAt).TotalSeconds);
                    OutboxMetrics.Attempts.Record(record.AttemptCount);
                }
                else
                {
                    // Confirm geldi ama kayıt bu sürede başka publisher'a geçmiş (lease dolmuş).
                    // Tekrar teslim tüketici tarafında message_id ile tekilleştirilir.
                    OutboxMetrics.StaleConfirm.Add(1);
                    logger.LogWarning("Outbox kaydı {Id} için stale confirm (message_id {MessageId})",
                        record.Id, envelope.MessageId);
                }

                return;
            }

            // mandatory + unroutable: routing hatası; başarı sayılmaz (B2 sözleşmesi).
            await store.MarkAttemptFailedAsync(record.Id, $"unroutable: {result.Detail}", nextLease, relay.MaxAttempts, cancellationToken);
            OutboxMetrics.PublishFailed.Add(1);
        }
        catch (TimeoutException)
        {
            // Confirm kaybı/karanlık bölge: mesaj broker'a ulaşmış olabilir; kayıt beklemede kalır
            // ve lease sonrası AYNI message_id ile tekrar yayınlanır (plan satır 301).
            await store.MarkAttemptFailedAsync(record.Id, "confirm zaman aşımı", nextLease, relay.MaxAttempts, cancellationToken);
            OutboxMetrics.PublishFailed.Add(1);
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            throw;
        }
        catch (Exception exception)
        {
            // Broker bağlantı hatası vb.: kayıt beklemede kalır (plan satır 300).
            await store.MarkAttemptFailedAsync(record.Id, exception.Message, nextLease, relay.MaxAttempts, cancellationToken);
            OutboxMetrics.PublishFailed.Add(1);
        }
    }

    /// <summary>Deneme sayısıyla üstel büyüyen lease (60s → 600s cap): başarısız publisher
    /// üst üste koşarak aynı kaydı yakmaz.</summary>
    private static TimeSpan LeaseFor(AgentOutboxRelaySettings relay, int attempt)
    {
        var backoff = Math.Min(attempt - 1, 4);
        var seconds = Math.Min(
            relay.ClaimLeaseSeconds * Math.Pow(2, backoff),
            relay.MaxClaimLeaseSeconds);
        return TimeSpan.FromSeconds(Math.Max(seconds, 1));
    }

    private async Task<bool> EnsurePublisherReadyAsync(CancellationToken cancellationToken)
    {
        if (_publisherReady)
        {
            return true;
        }

        await _startGate.WaitAsync(cancellationToken);
        try
        {
            if (_publisherReady)
            {
                return true;
            }

            await publisher.StartAsync(cancellationToken);
            _publisherReady = true;
            return true;
        }
        catch (Exception exception) when (exception is not OperationCanceledException)
        {
            // Broker kapalı: sessizce bir sonraki döngüye bırak (log tek satır, döngü başına bir kez).
            logger.LogWarning("Outbox publisher henüz hazır değil: {Message}", exception.Message);
            return false;
        }
        finally
        {
            _startGate.Release();
        }
    }
}
