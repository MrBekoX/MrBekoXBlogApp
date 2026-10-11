namespace BlogApp.Core.Application.Features.AgentFeature.Commands.AcceptAgentRunCommand;

/// <summary>
/// Kabul yanıtı: commit edilmiş run kimliği ve kabul durumu (plan satır 293).
/// ``Replay`` true ise istek daha önce kabul edilmişti ve mevcut run geri döndü;
/// yeni bir iş OLUŞTURULMADI (idempotent tekrar kabul). Bu durum Python'ın
/// ``agent.run.accepted`` olayından ayrı anlamlardır (plan satır 305).
/// </summary>
public sealed record AgentRunAcceptedDto(
    Guid RunId,
    Guid ConversationId,
    long TurnSequence,
    DateTime AcceptedAt,
    DateTime DeadlineAt,
    bool Replay);
