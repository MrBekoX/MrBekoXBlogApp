using MediatR;
using BlogApp.Core.Application.Common.Models;

namespace BlogApp.Core.Application.Features.AgentFeature.Commands.RecordAgentFeedbackCommand;

/// <summary>
/// Agent geri bildirim isteği (B10; plan tablosu: feedback). Sahiplik backend'de
/// doğrulanır; GuestSessionId sunucu tarafı misafir oturum çerezinden Presentation
/// tarafından verilir (K5). FeedbackKey istemcinin tek kullanımlık anahtarıdır —
/// aynı anahtarla gelen tekrar yeni kayıt üretmez.
/// </summary>
public sealed record RecordAgentFeedbackCommandRequest : IRequest<Result<AgentFeedbackDto>>
{
    public required Guid RunId { get; init; }

    /// <summary>1-5 puan; 1 = olumsuz, 5 = olumlu.</summary>
    public required int Rating { get; init; }

    public string? Comment { get; init; }

    public required string FeedbackKey { get; init; }

    public string? GuestSessionId { get; init; }
}
