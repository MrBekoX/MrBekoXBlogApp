using BlogApp.Core.Application.Features.AgentFeature.Services;
using Xunit;

namespace BlogApp.Presentation.Api.Tests.WhoAmI;

/// <summary>conversation_history sınırları (K6): son 3 soru/cevap (6 girdi), içerik ≤4000,
/// toplam ≤12000 karakter, kronolojik sıra, created_at AcceptedAt/TerminalAt.</summary>
public sealed class AgentConversationHistoryPolicyTests
{
    private static readonly DateTime Base = new(2026, 10, 22, 8, 0, 0, DateTimeKind.Utc);

    private static AgentHistoryCandidate Turn(long sequence, string question = "soru", string answer = "cevap") =>
        new(sequence, question, answer, Base.AddMinutes(sequence), Base.AddMinutes(sequence).AddSeconds(30));

    [Fact]
    public void Keeps_Last_Three_Pairs_In_Chronological_Order()
    {
        var turns = AgentConversationHistoryPolicy.Build(Enumerable.Range(1, 5).Select(i => Turn(i, $"s{i}", $"c{i}")));

        Assert.Equal(6, turns.Count);
        Assert.Equal(["s3", "c3", "s4", "c4", "s5", "c5"], turns.Select(t => t.Content));
        Assert.Equal(["user", "assistant", "user", "assistant", "user", "assistant"], turns.Select(t => t.Role));
        Assert.Equal("2026-10-22T08:03:00.000Z", turns[0].CreatedAt);
        Assert.Equal("2026-10-22T08:03:30.000Z", turns[1].CreatedAt);
    }

    [Fact]
    public void Truncates_Each_Content_To_Limit()
    {
        var turns = AgentConversationHistoryPolicy.Build([Turn(1, new string('s', 5000), new string('c', 4500))]);

        Assert.All(turns, t => Assert.Equal(AgentConversationHistoryPolicy.MaxContentChars, t.Content.Length));
    }

    [Fact]
    public void Truncation_Does_Not_Split_Surrogate_Pairs()
    {
        var text = new string('a', AgentConversationHistoryPolicy.MaxContentChars - 1) + "😀tail";

        var truncated = AgentConversationHistoryPolicy.Truncate(text);

        Assert.Equal(AgentConversationHistoryPolicy.MaxContentChars - 1, truncated.Length);
        Assert.False(char.IsHighSurrogate(truncated[^1]));
    }

    [Fact]
    public void Total_Limit_Drops_Oldest_Pairs_Without_Gaps()
    {
        // Her çift 4000 + 4000 = 8000 karakter: yalnız en yeni çift 12000 sınırına sığar.
        var big = new string('x', 4000);
        var turns = AgentConversationHistoryPolicy.Build([Turn(1, big, big), Turn(2, big, big), Turn(3, "yeni soru", big)]);

        Assert.Equal(2, turns.Count);
        Assert.Equal("yeni soru", turns[0].Content);
        Assert.True(turns.Sum(t => t.Content.Length) <= AgentConversationHistoryPolicy.MaxTotalChars);
    }

    [Fact]
    public void Skips_Empty_Answers()
    {
        var turns = AgentConversationHistoryPolicy.Build([Turn(1, "s1", "c1"), Turn(2, "s2", "   ")]);

        Assert.Equal(["s1", "c1"], turns.Select(t => t.Content));
    }

    [Fact]
    public void Extracts_Answer_Or_Report_From_Result_Snapshot()
    {
        Assert.Equal("cevap", AgentConversationHistoryComposer.ExtractAnswer("""{"answer":"cevap","report":"x"}"""));
        Assert.Equal("rapor", AgentConversationHistoryComposer.ExtractAnswer("""{"report":"rapor"}"""));
        Assert.Null(AgentConversationHistoryComposer.ExtractAnswer("""{"error_code":"timeout"}"""));
        Assert.Null(AgentConversationHistoryComposer.ExtractAnswer("bozuk"));
    }
}
