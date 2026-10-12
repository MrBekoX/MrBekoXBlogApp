namespace BlogApp.Core.Application.Features.AgentFeature.Commands.ResumeAgentRunCommand;

/// <summary>
/// Resume isteğinin kabul durumu (B10): "accepted" komut outbox'tadır (202 anlamlı);
/// "replay" için açık bir resume komutu zaten var. Graph devamı Python kontrol
/// consumer'ının B9 bağlantı noktasıdır; bu yanıt graph'ın sürdüğü anlamına gelmez.
/// </summary>
public sealed record AgentRunResumeDto(Guid RunId, string State, DateTimeOffset RequestedAt);
