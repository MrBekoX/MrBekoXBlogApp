using MediatR;
using BlogApp.Core.Application.Common.Models;

namespace BlogApp.Core.Application.Features.AgentFeature.Commands.ResumeAgentRunCommand;

/// <summary>
/// Agent işine devam isteği (B10; plan tablosu satır: resume). Sahiplik backend'de
/// doğrulanır; GuestSessionId sunucu tarafı misafir oturum çerezinden Presentation
/// tarafından verilir (K5), istemci owner alanı yetki kaynağı değildir.
/// </summary>
public sealed record ResumeAgentRunCommandRequest : IRequest<Result<AgentRunResumeDto>>
{
    public required Guid RunId { get; init; }

    /// <summary>İstemcinin gördüğü needs_input sürümü (event_sequence); doğrulama için.</summary>
    public long? ExpectedInputVersion { get; init; }

    /// <summary>İstemcinin gördüğü proposal sürümü (B9 sözleşmesi); doğrulama için.</summary>
    public long? ExpectedProposalVersion { get; init; }

    /// <summary>Sunucu tarafı misafir oturum kimliği; kimliği doğrulanmış kullanıcıda yok sayılır.</summary>
    public string? GuestSessionId { get; init; }
}
