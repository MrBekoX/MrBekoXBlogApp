using MediatR;
using BlogApp.Core.Application.Common.Models;

namespace BlogApp.Core.Application.Features.AgentFeature.Commands.CancelAgentRunCommand;

/// <summary>
/// Çalışan bir agent işinin iptal talebi (B7, plan satır 427). İptal kararı
/// backend'dedir: sahiplik doğrulanır, cancel komutu outbox kaydıyla TEK
/// transaction'da yazılır; terminal kararı agent tarafında kalıcı
/// cancel_intents + terminal-öncelik kuralıyla atomikleşir.
/// </summary>
public sealed record CancelAgentRunCommandRequest : IRequest<Result<AgentRunCancelDto>>
{
    /// <summary>İptal edilmek istenen çalıştırma (AgentRun.Id).</summary>
    public Guid RunId { get; init; }

    /// <summary>Opsiyonel gerekçe; sözleşme payload'ının reason alanına taşınır (≤2000 karakter).</summary>
    public string? Reason { get; init; }

    /// <summary>Kullanıcı oturumu yoksa sunucu tarafı misafir oturum kimliği (K5: Presentation üretir).</summary>
    public string? GuestSessionId { get; init; }
}
