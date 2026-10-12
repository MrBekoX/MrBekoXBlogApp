using BlogApp.Core.Domain.Enums;

namespace BlogApp.Core.Application.Common.Messaging;

/// <summary>Projection kararı: olayın AgentRun projection'ına uygulanıp uygulanmayacağı.</summary>
public enum AgentEventDecision
{
    /// <summary>Olay projection'a uygulanır (inbox kaydı applied ile yazılır).</summary>
    Apply,

    /// <summary>Tekrarlı teslim: aynı (consumer, message_id) inbox'ta zaten var; hiçbir şey yapılmaz.</summary>
    Duplicate,

    /// <summary>Sıra gerilemesi / terminal sonrası eski olay: inbox stale işaretlenir, projection değişmez.</summary>
    Stale
}

/// <summary>
/// B5 terminal-öncelik ve sıra kurallarının saf çekirdeği (plan B5 backend listesi):
/// - "Tekrarlı olayı aynı projection'a yeniden uygulama" → Duplicate.
/// - "Geç gelen eski olayın terminal durumu geriye götürmesini engelle" → Stale:
///   run terminal VEYA gelen sequence son uygulanan sequence'ten büyük değilken
///   non-terminal olay uygulanmaz.
/// - Terminal olay yalnız daha yeni sequence'liyse uygulanır (terminal-öncelik:
///   terminal her zaman aynı sequence yarışında son sözü söyler; iki terminal
///   çelişirse YÜKSEK sequence'li kazanır — teslim sırasına güvenilmez).
/// </summary>
public static class AgentRunEventProjectionRules
{
    public static AgentEventDecision Decide(
        bool duplicateDelivery,
        bool runIsTerminal,
        long lastAppliedSequence,
        long incomingSequence,
        bool incomingIsTerminal)
    {
        if (duplicateDelivery)
        {
            return AgentEventDecision.Duplicate;
        }

        // Terminal run'da yalnız DAHA YENİ terminal olay uygulanabilir (ör. ikinci
        // terminal; B7 cancel/completed yarışının projection tarafı). Eski progress,
        // eski terminal ve eşit sequence'li her şey stale'dir.
        if (incomingSequence <= lastAppliedSequence)
        {
            return AgentEventDecision.Stale;
        }

        if (runIsTerminal && !incomingIsTerminal)
        {
            return AgentEventDecision.Stale;
        }

        return AgentEventDecision.Apply;
    }
}
