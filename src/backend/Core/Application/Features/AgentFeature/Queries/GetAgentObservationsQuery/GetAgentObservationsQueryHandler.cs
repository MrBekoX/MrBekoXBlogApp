using System.Text.Json;
using System.Data.Common;
using BlogApp.Core.Application.Common.Interfaces.Data;
using BlogApp.Core.Application.Common.Messaging;
using BlogApp.Core.Application.Common.Models;
using BlogApp.Core.Application.Features.AgentFeature.Commands.RecordAgentFeedbackCommand;
using BlogApp.Core.Domain.Enums;
using MediatR;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging;

namespace BlogApp.Core.Application.Features.AgentFeature.Queries.GetAgentObservationsQuery;

/// <summary>Python agent şeması (agent.jobs) gözlem okumaları için bağlantı portu
/// (D011: tablo sahipliği Python'dadır; yönetim gözlemi salt OKUR, FK kurmaz).
/// Uygulaması Presentation DI kablolamasındadır.</summary>
public interface IAgentSystemDbConnectionFactory
{
    Task<DbConnection> OpenConnectionAsync(CancellationToken cancellationToken = default);
}

/// <summary>
/// B10 yönetim gözlem sorgusu (plan admin listesi): "Queue ve job backlog, en eski iş
/// yaşı. Outbox yayın gecikmesi ve confirm hatası. Duplicate/inbox sayıları, retry ve
/// DLQ. İş süreleri, lease recovery ve iptal gecikmesi. Agent mod, token, araç, kalite
/// ve geri bildirim ölçümleri." — HEPSİ mevcut tabloların OKUMASIYLA üretilir; yeni
/// ağır altyapı kurulmaz. Python ``agent`` şeması ayrı salt-okunur bağlantıyla okunur;
/// tablo yoksa bölüm null döner (hata değil).
/// </summary>
public sealed class GetAgentObservationsQueryHandler(
    IApplicationDbContext dbContext,
    IAgentSystemDbConnectionFactory? systemDbConnectionFactory,
    ILogger<GetAgentObservationsQueryHandler> logger)
    : IRequestHandler<GetAgentObservationsQueryRequest, Result<AgentObservationsDto>>
{
    private const int SampleLimit = 5000;

    public async Task<Result<AgentObservationsDto>> Handle(GetAgentObservationsQueryRequest request, CancellationToken cancellationToken)
    {
        var windowHours = request.WindowHours is > 0 and <= 720 ? request.WindowHours : 24;
        var now = DateTime.UtcNow;
        var windowStart = now.AddHours(-windowHours);

        // ---- Kabul backlog'u (agent_runs) ----
        var activeRuns = await dbContext.AgentRuns.AsNoTracking()
            .CountAsync(r => r.Status == AgentRunStatus.Accepted, cancellationToken);
        var oldestAcceptedAt = await dbContext.AgentRuns.AsNoTracking()
            .Where(r => r.Status == AgentRunStatus.Accepted)
            .OrderBy(r => r.AcceptedAt)
            .Select(r => (DateTime?)r.AcceptedAt)
            .FirstOrDefaultAsync(cancellationToken);
        var runsLastWindow = await dbContext.AgentRuns.AsNoTracking()
            .CountAsync(r => r.AcceptedAt >= windowStart, cancellationToken);

        // ---- Outbox: derinlikler + yayın gecikmesi + confirm/attempt hataları ----
        var outboxPending = await dbContext.OutboxMessages.AsNoTracking()
            .CountAsync(m => m.Status == AgentOutboxStatus.Pending, cancellationToken);
        var outboxClaimed = await dbContext.OutboxMessages.AsNoTracking()
            .CountAsync(m => m.Status == AgentOutboxStatus.Claimed, cancellationToken);
        var outboxPublished = await dbContext.OutboxMessages.AsNoTracking()
            .CountAsync(m => m.Status == AgentOutboxStatus.Published, cancellationToken);
        var outboxDead = await dbContext.OutboxMessages.AsNoTracking()
            .CountAsync(m => m.Status == AgentOutboxStatus.DeadLettered, cancellationToken);

        var oldestPendingAt = await dbContext.OutboxMessages.AsNoTracking()
            .Where(m => m.Status == AgentOutboxStatus.Pending)
            .OrderBy(m => m.CreatedAt)
            .Select(m => (DateTime?)m.CreatedAt)
            .FirstOrDefaultAsync(cancellationToken);

        var publishedWindow = await dbContext.OutboxMessages.AsNoTracking()
            .Where(m => m.Status == AgentOutboxStatus.Published
                        && m.PublishedAt != null
                        && m.PublishedAt >= windowStart)
            .Select(m => new OutboxRow(m.CreatedAt, m.PublishedAt!.Value, m.AttemptCount, m.LastError != null))
            .Take(SampleLimit)
            .ToListAsync(cancellationToken);

        var latencySeconds = publishedWindow
            .Select(m => (m.PublishedAt - m.CreatedAt).TotalSeconds)
            .Where(x => x >= 0)
            .OrderBy(x => x)
            .ToList();

        // ---- Projection inbox: duplicate/stale/quarantined sayıları ----
        var applied = await dbContext.AgentEventInboxes.AsNoTracking()
            .CountAsync(i => i.ConsumerName == AgentRunEventProjectionHandler.ConsumerName && i.Status == "applied", cancellationToken);
        var duplicates = await dbContext.AgentEventInboxes.AsNoTracking()
            .CountAsync(i => i.ConsumerName == AgentRunEventProjectionHandler.ConsumerName && i.Status == "duplicate", cancellationToken);
        var stale = await dbContext.AgentEventInboxes.AsNoTracking()
            .CountAsync(i => i.ConsumerName == AgentRunEventProjectionHandler.ConsumerName && i.Status == "stale", cancellationToken);
        var quarantined = await dbContext.AgentEventInboxes.AsNoTracking()
            .CountAsync(i => i.ConsumerName == AgentRunEventProjectionHandler.ConsumerName && i.Status == "quarantined", cancellationToken);

        // ---- İş süreleri / mod dağılımı / terminal dağılımı / iptal gecikmesi ----
        // IsTerminal() yardımcı metodu SQL'e çevrilmez; terminal kümesi açık yazılır.
        AgentRunStatus[] terminalStatuses = AgentRunStatusRules.TerminalStatuses.ToArray();
        var terminalRuns = await dbContext.AgentRuns.AsNoTracking()
            .Where(r => terminalStatuses.Contains(r.Status)
                        && r.TerminalAt != null && r.TerminalAt >= windowStart)
            .Select(r => new RunRow(
                r.Id, r.Status, r.ModePreference, r.SelectedMode,
                r.AcceptedAt, r.TerminalAt!.Value, r.ResultJson))
            .Take(SampleLimit)
            .ToListAsync(cancellationToken);

        var runSeconds = terminalRuns
            .Select(r => (r.TerminalAt - r.AcceptedAt).TotalSeconds)
            .Where(x => x >= 0)
            .OrderBy(x => x)
            .ToList();

        var modeCounts = terminalRuns
            .GroupBy(r => string.IsNullOrEmpty(r.SelectedMode) ? r.ModePreference : r.SelectedMode)
            .ToDictionary(g => g.Key, g => g.Count());

        var terminalCounts = terminalRuns
            .GroupBy(r => r.Status.ToString())
            .ToDictionary(g => g.Key, g => g.Count());

        var completedWithUnresolved = terminalRuns.Count(r =>
            r.Status == AgentRunStatus.Completed && ContainsUnresolvedQuestions(r.ResultJson));

        // İptal gecikmesi: cancelled run + o run'ın ilk cancel komut kaydı (backend
        // outbox CreatedAt) → terminal zamanı; yalnız pencere içindeki cancelled'lar.
        var cancelledIds = terminalRuns
            .Where(r => r.Status == AgentRunStatus.Cancelled)
            .Select(r => r.RunId)
            .ToList();
        var cancelRequestedAt = cancelledIds.Count == 0
            ? new Dictionary<Guid, DateTime>()
            : await dbContext.OutboxMessages.AsNoTracking()
                .Where(m => m.MessageType == AgentMessageTypes.CancellationRequested
                            && m.RunId != null
                            && cancelledIds.Contains(m.RunId.Value))
                .GroupBy(m => m.RunId!.Value)
                .Select(g => new { RunId = g.Key, FirstRequestedAt = g.Min(m => m.CreatedAt) })
                .ToDictionaryAsync(x => x.RunId, x => x.FirstRequestedAt, cancellationToken);

        var cancelLatencies = terminalRuns
            .Where(r => r.Status == AgentRunStatus.Cancelled
                        && cancelRequestedAt.TryGetValue(r.RunId, out var requestedAt)
                        && r.TerminalAt >= requestedAt)
            .Select(r => (r.TerminalAt - cancelRequestedAt[r.RunId]).TotalSeconds)
            .OrderBy(x => x)
            .ToList();

        // ---- Geri bildirim özeti (B10 feedback kayıtları) ----
        var feedbackDetails = await dbContext.AgentEventInboxes.AsNoTracking()
            .Where(i => i.ConsumerName == ProjectionAgentFeedbackStore.ConsumerName)
            .OrderByDescending(i => i.CreatedAt)
            .Take(2000)
            .Select(i => i.Detail)
            .ToListAsync(cancellationToken);

        var ratings = feedbackDetails
            .Where(detail => TryReadRating(detail, out _))
            .Select(detail => ReadRating(detail))
            .ToList();

        // ---- Python agent şeması (guarded, salt okunur) ----
        JobObservations? jobs = null;
        if (systemDbConnectionFactory is not null)
        {
            try
            {
                jobs = await ObserveJobsAsync(systemDbConnectionFactory, cancellationToken);
            }
            catch (Exception exception) when (exception is not OperationCanceledException)
            {
                logger.LogWarning(exception,
                    "[AgentObservations] agent şeması gözlemi okunamadı; bölüm null döner");
            }
        }

        return Result<AgentObservationsDto>.Success(new AgentObservationsDto
        {
            GeneratedAt = new DateTimeOffset(now, TimeSpan.Zero),
            WindowHours = windowHours,
            Acceptance = new AgentAcceptanceObservationsDto
            {
                ActiveRuns = activeRuns,
                OldestActiveRunAgeMinutes = oldestAcceptedAt is { } accepted
                    ? (now - accepted).TotalMinutes
                    : null,
                RunsLastWindow = runsLastWindow,
            },
            Outbox = new AgentOutboxObservationsDto
            {
                Pending = outboxPending,
                Claimed = outboxClaimed,
                Published = outboxPublished,
                DeadLettered = outboxDead,
                OldestPendingAgeMinutes = oldestPendingAt is { } pendingAt
                    ? (now - pendingAt).TotalMinutes
                    : null,
                AveragePublishLatencySeconds = latencySeconds.Count > 0 ? latencySeconds.Average() : null,
                P95PublishLatencySeconds = latencySeconds.Count > 0 ? Percentile(latencySeconds, 0.95) : null,
                RecordsWithPublishErrors = publishedWindow.Count(m => m.AttemptCount > 0 || m.HadError),
                AttemptSum = publishedWindow.Sum(m => m.AttemptCount),
            },
            Projection = new AgentProjectionObservationsDto
            {
                Applied = applied,
                Duplicates = duplicates,
                Stale = stale,
                Quarantined = quarantined,
            },
            Runs = new AgentRunsObservationsDto
            {
                AverageRunSeconds = runSeconds.Count > 0 ? runSeconds.Average() : null,
                MaxRunSeconds = runSeconds.Count > 0 ? runSeconds[^1] : null,
                AverageCancelLatencySeconds = cancelLatencies.Count > 0 ? cancelLatencies.Average() : null,
                ModeCounts = modeCounts,
                TerminalCounts = terminalCounts,
                CompletedWithUnresolvedQuestions = completedWithUnresolved,
            },
            Feedback = new AgentFeedbackObservationsDto
            {
                Total = ratings.Count,
                AverageRating = ratings.Count > 0 ? ratings.Average() : null,
                RatingCounts = ratings
                    .GroupBy(r => r)
                    .ToDictionary(g => g.Key, g => g.Count()),
            },
            Jobs = jobs is null
                ? null
                : new AgentJobsObservationsDto
                {
                    BacklogByQueue = jobs.BacklogByQueue,
                    OldestBacklogAgeMinutes = jobs.OldestBacklogAgeMinutes,
                    ExpiredLeaseRunning = jobs.ExpiredLeaseRunning,
                    StatusCounts = jobs.StatusCounts,
                    JobsWithRetries = jobs.JobsWithRetries,
                },
        });
    }

    private sealed record OutboxRow(DateTime CreatedAt, DateTime PublishedAt, int AttemptCount, bool HadError);

    private sealed record RunRow(
        Guid RunId, AgentRunStatus Status, string ModePreference, string? SelectedMode,
        DateTime AcceptedAt, DateTime TerminalAt, string? ResultJson);

    private sealed record JobObservations
    {
        public required IReadOnlyDictionary<string, int> BacklogByQueue { get; init; }

        public double? OldestBacklogAgeMinutes { get; init; }

        public required int ExpiredLeaseRunning { get; init; }

        public required IReadOnlyDictionary<string, int> StatusCounts { get; init; }

        public required int JobsWithRetries { get; init; }
    }

    private static double Percentile(List<double> sorted, double p)
    {
        var index = (int)Math.Ceiling(p * sorted.Count) - 1;
        return sorted[Math.Clamp(index, 0, sorted.Count - 1)];
    }

    private static bool ContainsUnresolvedQuestions(string? resultJson)
    {
        if (string.IsNullOrWhiteSpace(resultJson))
        {
            return false;
        }

        try
        {
            using var document = JsonDocument.Parse(resultJson);
            return document.RootElement.ValueKind == JsonValueKind.Object
                   && document.RootElement.TryGetProperty("unresolved_questions", out var questions)
                   && questions.ValueKind == JsonValueKind.Array
                   && questions.GetArrayLength() > 0;
        }
        catch (JsonException)
        {
            return false;
        }
    }

    private static bool TryReadRating(string? detail, out int rating)
    {
        rating = 0;
        if (string.IsNullOrWhiteSpace(detail))
        {
            return false;
        }

        try
        {
            using var document = JsonDocument.Parse(detail);
            if (document.RootElement.ValueKind == JsonValueKind.Object
                && document.RootElement.TryGetProperty("rating", out var value))
            {
                var candidate = value.ValueKind == JsonValueKind.String
                    ? value.GetString()
                    : value.ValueKind == JsonValueKind.Number ? value.GetRawText() : null;
                if (int.TryParse(candidate, out var parsed) && parsed is >= 1 and <= 5)
                {
                    rating = parsed;
                    return true;
                }
            }

            return false;
        }
        catch (JsonException)
        {
            return false;
        }
    }

    private static int ReadRating(string? detail)
    {
        TryReadRating(detail, out var rating);
        return rating;
    }

    private static async Task<JobObservations?> ObserveJobsAsync(
        IAgentSystemDbConnectionFactory connectionFactory, CancellationToken cancellationToken)
    {
        await using var connection = await connectionFactory.OpenConnectionAsync(cancellationToken);

        // agent şeması henüz migrate edilmemişse bölüm null döner (hata değil).
        if (await ExecuteScalarAsync(connection, "SELECT to_regclass('agent.jobs')::text", cancellationToken) is null)
        {
            return null;
        }

        var statusCounts = new Dictionary<string, int>();
        await using (var command = connection.CreateCommand())
        {
            command.CommandText = "SELECT status, count(*) FROM agent.jobs GROUP BY status";
            await using var reader = await command.ExecuteReaderAsync(cancellationToken);
            while (await reader.ReadAsync(cancellationToken))
            {
                statusCounts[reader.GetString(0)] = (int)reader.GetInt64(1);
            }
        }

        var backlogByQueue = new Dictionary<string, int>();
        double? oldestBacklogMinutes = null;
        await using (var command = connection.CreateCommand())
        {
            command.CommandText = """
                SELECT queue_class, count(*), min(accepted_at) FROM agent.jobs
                WHERE status IN ('accepted', 'queued')
                GROUP BY queue_class
                """;
            await using var reader = await command.ExecuteReaderAsync(cancellationToken);
            while (await reader.ReadAsync(cancellationToken))
            {
                backlogByQueue[reader.GetString(0)] = (int)reader.GetInt64(1);
                if (!reader.IsDBNull(2))
                {
                    oldestBacklogMinutes = (DateTime.UtcNow - reader.GetDateTime(2)).TotalMinutes;
                }
            }
        }

        var expiredLease = (int?)ToLong(await ExecuteScalarAsync(connection,
            "SELECT count(*) FROM agent.jobs WHERE status = 'running' AND lease_until IS NOT NULL AND lease_until < now()",
            cancellationToken));
        var withRetries = (int?)ToLong(await ExecuteScalarAsync(connection,
            "SELECT count(*) FROM agent.jobs WHERE execution_attempt > 0 AND status IN ('accepted', 'queued', 'running')",
            cancellationToken));

        return new JobObservations
        {
            BacklogByQueue = backlogByQueue,
            OldestBacklogAgeMinutes = oldestBacklogMinutes,
            ExpiredLeaseRunning = expiredLease ?? 0,
            StatusCounts = statusCounts,
            JobsWithRetries = withRetries ?? 0,
        };
    }

    private static async Task<object?> ExecuteScalarAsync(
        DbConnection connection, string sql, CancellationToken cancellationToken)
    {
        await using var command = connection.CreateCommand();
        command.CommandText = sql;
        var result = await command.ExecuteScalarAsync(cancellationToken);
        return result is DBNull ? null : result;
    }

    private static long? ToLong(object? value) => value switch
    {
        null => null,
        long number => number,
        int number => number,
        decimal number => (long)number,
        _ => long.TryParse(value.ToString(), out var parsed) ? parsed : null,
    };
}
