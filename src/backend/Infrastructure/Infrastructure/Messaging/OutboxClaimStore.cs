using BlogApp.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;

namespace BlogApp.Infrastructure.Messaging;

/// <summary>Claim (lease) ile alınmış tek outbox kaydı; EnvelopeJson yayın için taşınır.</summary>
public sealed record OutboxClaimedRecord(
    Guid Id,
    string MessageId,
    string Exchange,
    string RoutingKey,
    string CorrelationId,
    Guid? RunId,
    string EnvelopeJson,
    int AttemptCount,
    DateTime CreatedAt);

/// <summary>
/// Outbox claim/market işlemleri — tek UPDATE ... WHERE IN (SELECT ... FOR UPDATE SKIP LOCKED)
/// ile atomik lease (plan satır 297 ve 302: iki publisher aynı kaydı kontrolsüz alamaz).
/// Postgres somut SQL'i buradadır; EF Change Tracker'a dokunmaz.
/// </summary>
public sealed class OutboxClaimStore(AppDbContext context)
{
    public async Task<IReadOnlyList<OutboxClaimedRecord>> ClaimBatchAsync(
        string claimedBy,
        int batchSize,
        TimeSpan lease,
        CancellationToken cancellationToken)
    {
        var now = DateTime.UtcNow;
        var leaseUntil = now.Add(lease);

        var connection = context.Database.GetDbConnection();
        if (connection.State != System.Data.ConnectionState.Open)
        {
            await connection.OpenAsync(cancellationToken);
        }

        await using var command = connection.CreateCommand();
        command.CommandText = """
            UPDATE outbox_messages AS o
            SET "Status" = 'Claimed',
                "ClaimedBy" = @claimed_by,
                "ClaimedAt" = @now,
                "ClaimLeaseUntil" = @lease_until,
                "AttemptCount" = o."AttemptCount" + 1,
                "LastAttemptAt" = @now,
                "UpdatedAt" = @now
            WHERE o."Id" IN (
                SELECT c."Id"
                FROM outbox_messages AS c
                WHERE c."Status" = 'Pending'
                   OR (c."Status" = 'Claimed' AND (c."ClaimLeaseUntil" IS NULL OR c."ClaimLeaseUntil" < @now))
                ORDER BY c."CreatedAt"
                LIMIT @batch
                FOR UPDATE SKIP LOCKED
            )
            RETURNING o."Id", o."MessageId", o."Exchange", o."RoutingKey",
                      o."CorrelationId", o."RunId", o."EnvelopeJson", o."AttemptCount", o."CreatedAt";
            """;

        AddParameter(command, "claimed_by", claimedBy);
        AddParameter(command, "now", now);
        AddParameter(command, "lease_until", leaseUntil);
        AddParameter(command, "batch", batchSize);

        var records = new List<OutboxClaimedRecord>();
        await using var reader = await command.ExecuteReaderAsync(cancellationToken);
        while (await reader.ReadAsync(cancellationToken))
        {
            records.Add(new OutboxClaimedRecord(
                Id: reader.GetGuid(0),
                MessageId: reader.GetString(1),
                Exchange: reader.GetString(2),
                RoutingKey: reader.GetString(3),
                CorrelationId: reader.GetString(4),
                RunId: reader.IsDBNull(5) ? null : reader.GetGuid(5),
                EnvelopeJson: reader.GetString(6),
                AttemptCount: reader.GetInt32(7),
                CreatedAt: reader.GetDateTime(8)));
        }

        return records;
    }

    /// <summary>Confirm sonrası tamamlama; kayıt bu arada başka publisher tarafından yeniden
    /// alınmışsa (lease dolmuş) etkilenmez — stale confirm sessizce ölçülür.</summary>
    public async Task<bool> MarkPublishedAsync(Guid id, DateTime publishedAt, CancellationToken cancellationToken)
    {
        var now = DateTime.UtcNow;
        var connection = context.Database.GetDbConnection();
        if (connection.State != System.Data.ConnectionState.Open)
        {
            await connection.OpenAsync(cancellationToken);
        }

        await using var command = connection.CreateCommand();
        command.CommandText = """
            UPDATE outbox_messages
            SET "Status" = 'Published',
                "PublishedAt" = @published_at,
                "LastError" = NULL,
                "ClaimedBy" = NULL,
                "ClaimedAt" = NULL,
                "ClaimLeaseUntil" = NULL,
                "UpdatedAt" = @now
            WHERE "Id" = @id AND "Status" = 'Claimed';
            """;

        AddParameter(command, "published_at", publishedAt);
        AddParameter(command, "now", now);
        AddParameter(command, "id", id);
        return await command.ExecuteNonQueryAsync(cancellationToken) > 0;
    }

    /// <summary>Başarısız deneme: kayıt beklemede kalır (Claimed + yeni lease) veya deneme üst
    /// sınırına ulaşıldıysa DeadLettered olur (plan satır 300 + sınırsız tekrar yasağı).</summary>
    public async Task MarkAttemptFailedAsync(
        Guid id,
        string error,
        TimeSpan nextLease,
        int maxAttempts,
        CancellationToken cancellationToken)
    {
        var now = DateTime.UtcNow;
        var leaseUntil = now.Add(nextLease);
        var connection = context.Database.GetDbConnection();
        if (connection.State != System.Data.ConnectionState.Open)
        {
            await connection.OpenAsync(cancellationToken);
        }

        await using var command = connection.CreateCommand();
        command.CommandText = """
            UPDATE outbox_messages
            SET "LastError" = @error,
                "LastAttemptAt" = @now,
                "UpdatedAt" = @now,
                "Status" = CASE WHEN "AttemptCount" >= @max THEN 'DeadLettered' ELSE "Status" END,
                "ClaimLeaseUntil" = CASE WHEN "AttemptCount" >= @max THEN NULL ELSE @lease_until END,
                "ClaimedBy" = CASE WHEN "AttemptCount" >= @max THEN NULL ELSE "ClaimedBy" END,
                "ClaimedAt" = CASE WHEN "AttemptCount" >= @max THEN NULL ELSE "ClaimedAt" END
            WHERE "Id" = @id AND "Status" = 'Claimed';
            """;

        AddParameter(command, "error", error is { Length: > 4000 } ? error[..4000] : error);
        AddParameter(command, "now", now);
        AddParameter(command, "max", maxAttempts);
        AddParameter(command, "lease_until", leaseUntil);
        AddParameter(command, "id", id);
        await command.ExecuteNonQueryAsync(cancellationToken);
    }

    private static void AddParameter(System.Data.Common.DbCommand command, string name, object? value)
    {
        var parameter = command.CreateParameter();
        parameter.ParameterName = name;
        parameter.Value = value ?? DBNull.Value;
        command.Parameters.Add(parameter);
    }
}
