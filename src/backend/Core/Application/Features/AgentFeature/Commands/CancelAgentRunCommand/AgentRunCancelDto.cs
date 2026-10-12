namespace BlogApp.Core.Application.Features.AgentFeature.Commands.CancelAgentRunCommand;

/// <summary>
/// İptal isteğinin kabul yanıtı. Cancel intent kaydı TERMINAL DEĞİLDİR
/// (plan satır 431): arayüz bu yanıtta "iptal isteniyor" durumunu gösterir;
/// terminal sonuç agent.run.cancelled olayı projection'ıyla gelir (B5).
/// </summary>
public sealed record AgentRunCancelDto(
    Guid RunId,
    /// <summary>requested: komut outbox'a yazıldı; already_terminal: iş zaten terminal,
    /// istek kaydedilmedi; replay: aynı iş için açık cancel komutu zaten var (idempotent).</summary>
    string Outcome,
    DateTimeOffset RequestedAt);
