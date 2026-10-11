namespace BlogApp.Core.Application.Common.Messaging;

/// <summary>
/// Run başına monoton event_sequence koruması (plan satır 237, B0 K6): eşit veya düşük sequence'li
/// olay reddedilir; broker tekrar teslimi deduplication'ın sorumluluğundadır, sıra garantisi bu
/// korumadan gelir. Backend projection terminal durmdan sonra gelen gerilemeleri uygulamaz.
/// </summary>
public sealed class AgentEventSequenceGuard
{
    private readonly object _lock = new();
    private readonly Dictionary<string, long> _lastSequenceByRun = new(StringComparer.Ordinal);

    public bool TryAccept(string runId, long eventSequence,
        [System.Diagnostics.CodeAnalysis.NotNullWhen(false)] out AgentContractError? error)
    {
        lock (_lock)
        {
            if (_lastSequenceByRun.TryGetValue(runId, out var last))
            {
                if (eventSequence <= last)
                {
                    error = new AgentContractError(
                        AgentContractErrorCategory.WrongType,
                        "event_sequence",
                        $"run '{runId}' için event_sequence gerilemesi: son kabul edilen {last}, gelen {eventSequence}");
                    return false;
                }
            }

            _lastSequenceByRun[runId] = eventSequence;
            error = null;
            return true;
        }
    }
}
