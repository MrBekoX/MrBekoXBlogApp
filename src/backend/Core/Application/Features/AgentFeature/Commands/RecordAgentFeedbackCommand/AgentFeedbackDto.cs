namespace BlogApp.Core.Application.Features.AgentFeature.Commands.RecordAgentFeedbackCommand;

/// <summary>
/// Geri bildirim kayıt durumu: "recorded" yeni kayıt yazıldı; "replay" aynı
/// anahtarlı kayıt zaten vardı (idempotent tekrar).
/// </summary>
public sealed record AgentFeedbackDto(Guid RunId, string State, DateTimeOffset RecordedAt);
