using System.Text.Json;
using BlogApp.Core.Application.Common.Interfaces.Data;
using BlogApp.Core.Application.Common.Messaging;
using BlogApp.Core.Domain.Enums;
using Microsoft.EntityFrameworkCore;

namespace BlogApp.Core.Application.Features.AgentFeature.Services;

/// <summary>Geçmişe girebilecek önceki tur: sunum denetiminden geçmiş tamamlanmış run.</summary>
public sealed record AgentHistoryCandidate(
    long TurnSequence,
    string Question,
    string Answer,
    DateTime AcceptedAt,
    DateTime? TerminalAt);

/// <summary>
/// conversation_history sınırlarının saf çekirdeği (K6): en yeni turlardan geriye doğru en fazla
/// <see cref="MaxTurns"/> konuşma girdisi (3 soru/cevap), içerik başına ≤ <see cref="MaxContentChars"/>
/// karakter, toplam ≤ <see cref="MaxTotalChars"/> karakter; çıktı kronolojiktir (user, assistant, ...).
/// Toplam sınırı aşan ilk eski tur ve öncesi alınmaz (araya boşluk girmez). Geçmiş kanıt değildir;
/// yalnız takip sorusu çözümlemesine bağlam verir.
/// </summary>
public static class AgentConversationHistoryPolicy
{
    public const int MaxTurns = 6;
    public const int MaxContentChars = 4000;
    public const int MaxTotalChars = 12000;

    public static IReadOnlyList<AgentConversationTurn> Build(IEnumerable<AgentHistoryCandidate> candidates)
    {
        var pairs = new List<(AgentHistoryCandidate Source, string Question, string Answer)>();
        var total = 0;
        foreach (var candidate in candidates.OrderByDescending(c => c.TurnSequence))
        {
            if ((pairs.Count + 1) * 2 > MaxTurns)
            {
                break;
            }

            var question = Truncate(candidate.Question.Trim());
            var answer = Truncate(candidate.Answer.Trim());
            if (question.Length == 0 || answer.Length == 0)
            {
                continue;
            }

            if (total + question.Length + answer.Length > MaxTotalChars)
            {
                break;
            }

            pairs.Add((candidate, question, answer));
            total += question.Length + answer.Length;
        }

        pairs.Reverse();
        var turns = new List<AgentConversationTurn>(pairs.Count * 2);
        foreach (var (source, question, answer) in pairs)
        {
            turns.Add(new AgentConversationTurn
            {
                Role = "user",
                Content = question,
                CreatedAt = FormatUtc(source.AcceptedAt),
            });
            turns.Add(new AgentConversationTurn
            {
                Role = "assistant",
                Content = answer,
                CreatedAt = FormatUtc(source.TerminalAt ?? source.AcceptedAt),
            });
        }

        return turns;
    }

    /// <summary>İçeriği karakter sınırına keser; vekil (surrogate) çiftini bölmez.</summary>
    public static string Truncate(string value)
    {
        if (value.Length <= MaxContentChars)
        {
            return value;
        }

        var cut = MaxContentChars;
        if (char.IsHighSurrogate(value[cut - 1]))
        {
            cut--;
        }

        return value[..cut];
    }

    private static string FormatUtc(DateTime value) =>
        AgentCommandEnvelopeComposer.FormatUtc(new DateTimeOffset(DateTime.SpecifyKind(value, DateTimeKind.Utc)));
}

/// <summary>v2 execute komutunun conversation_history derleyicisi (K6).</summary>
public interface IAgentConversationHistoryComposer
{
    Task<IReadOnlyList<AgentConversationTurn>> ComposeAsync(
        string ownerKey,
        Guid conversationId,
        string conversationTopic,
        CancellationToken cancellationToken = default);
}

/// <summary>
/// Aynı sahip + aynı konuşma + aynı konu için önceki completed/partially_completed turları
/// TurnSequence sırasıyla derler. Her aday, GET/SignalR/replay ile AYNI sunum denetiminden
/// (<see cref="IAgentResultPresentationGuard"/>) geçer: eski/geri çekilmiş profil sürümüne dayanan,
/// maskelenmiş veya yayından kalkmış makaleye dayanan cevaplar geçmişe DÖNMEZ. Başka sahibin
/// veya başka konunun metni sorgu koşullarıyla dışarıda kalır.
/// </summary>
public sealed class AgentConversationHistoryComposer(
    IApplicationDbContext dbContext,
    IAgentResultPresentationGuard presentationGuard) : IAgentConversationHistoryComposer
{
    /// <summary>Denetlenecek en yeni aday tur sayısı (maskelenen turlar atlanırken sınırsız tarama yapılmaz).</summary>
    public const int CandidateWindow = 12;

    public async Task<IReadOnlyList<AgentConversationTurn>> ComposeAsync(
        string ownerKey,
        Guid conversationId,
        string conversationTopic,
        CancellationToken cancellationToken = default)
    {
        var rows = await dbContext.AgentRuns
            .AsNoTracking()
            .Where(r => r.ConversationId == conversationId
                        && r.OwnerKey == ownerKey
                        && (r.Status == AgentRunStatus.Completed || r.Status == AgentRunStatus.PartiallyCompleted)
                        && r.ResultJson != null)
            .OrderByDescending(r => r.TurnSequence)
            .Take(CandidateWindow)
            .Select(r => new
            {
                r.Id,
                r.ArticleId,
                r.ResultJson,
                r.ContextSnapshotJson,
                r.Question,
                r.TurnSequence,
                r.AcceptedAt,
                r.TerminalAt,
            })
            .ToListAsync(cancellationToken);

        var candidates = new List<AgentHistoryCandidate>();
        foreach (var row in rows)
        {
            if (candidates.Count * 2 >= AgentConversationHistoryPolicy.MaxTurns)
            {
                break;
            }

            if (AgentRunWireContext.Parse(row.ContextSnapshotJson).ConversationTopic != conversationTopic)
            {
                continue;
            }

            var presentation = await presentationGuard.CheckAsync(
                new AgentRunResultContext(row.Id, row.ArticleId, row.ResultJson, row.ContextSnapshotJson),
                cancellationToken);
            if (!presentation.IsPresentable)
            {
                continue;
            }

            var answer = ExtractAnswer(row.ResultJson);
            if (string.IsNullOrWhiteSpace(answer))
            {
                continue;
            }

            candidates.Add(new AgentHistoryCandidate(row.TurnSequence, row.Question, answer, row.AcceptedAt, row.TerminalAt));
        }

        return AgentConversationHistoryPolicy.Build(candidates);
    }

    /// <summary>Terminal snapshot'tan asistan metni (answer, yoksa report); bozuk JSON → null.</summary>
    public static string? ExtractAnswer(string? resultJson)
    {
        if (string.IsNullOrWhiteSpace(resultJson))
        {
            return null;
        }

        try
        {
            using var document = JsonDocument.Parse(resultJson);
            var root = document.RootElement;
            if (root.ValueKind != JsonValueKind.Object)
            {
                return null;
            }

            foreach (var name in (string[])["answer", "report"])
            {
                if (root.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.String
                    && !string.IsNullOrWhiteSpace(value.GetString()))
                {
                    return value.GetString();
                }
            }

            return null;
        }
        catch (JsonException)
        {
            return null;
        }
    }
}
