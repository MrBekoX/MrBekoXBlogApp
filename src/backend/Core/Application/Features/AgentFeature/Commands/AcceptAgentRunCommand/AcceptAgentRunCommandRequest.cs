using MediatR;
using BlogApp.Core.Application.Common.Models;

namespace BlogApp.Core.Application.Features.AgentFeature.Commands.AcceptAgentRunCommand;

/// <summary>
/// Agent iş kabul komutu (plan satır 285-293): oturum doğrulama, makale erişim + limit kontrolü,
/// idempotency, run kaydı + komut outbox kaydı tek transaction'da; commit sonrası accepted run_id.
/// REST controller B10'da eklenir; komut bugün doğrudan MediatR üzerinden çağrılır.
/// </summary>
public sealed record AcceptAgentRunCommandRequest : IRequest<Result<AgentRunAcceptedDto>>
{
    public required string Question { get; init; }

    public required string Language { get; init; }

    /// <summary>auto | fast | analysis | deep_research (B1 payload Choice kümesi).</summary>
    public required string ModePreference { get; init; }

    public string BudgetProfile { get; init; } = "standard";

    /// <summary>Soru bir makale bağlamında sorulduysa makale kimliği; erişim kontrolü backend'de yapılır.</summary>
    public Guid? ArticleId { get; init; }

    /// <summary>Seçili paragraf/kod bölümü; payload selected_text alanına taşınır (≤20000).</summary>
    public string? SelectedText { get; init; }

    /// <summary>Takip sorusu için mevcut konuşma; verilmezse yeni konuşma açılır. Sahiplik backend'de doğrulanır.</summary>
    public Guid? ConversationId { get; init; }

    /// <summary>İstemci idempotency anahtarı; aynı anahtar aynı payload ile gelirse mevcut run döner,
    /// farklı payload ile gelirse çakışma döndürülür (plan satır 289-290).</summary>
    public required string IdempotencyKey { get; init; }

    /// <summary>Sunucu tarafı misafir oturum kimliği (K5: Presentation HttpOnly cookie üretir);
    /// kimliği doğrulanmış kullanıcıda yok sayılır.</summary>
    public string? GuestSessionId { get; init; }

    /// <summary>Konu (K1): <c>auto</c> (varsayılan) | <c>who_am_i</c>. Endpoint trim + küçük harf
    /// normalize eder; konu bir sohbet için sabittir. who_am_i makale bağlamı ve selected_text
    /// taşıyamaz; /research uç noktasıyla kullanılamaz.</summary>
    public string ConversationTopic { get; init; } = "auto";

    /// <summary>İstek /research (açık derin araştırma) uç noktasından geldiyse true; who_am_i ile
    /// birlikte reddedilir (profil konusu web araştırması başlatamaz).</summary>
    public bool IsResearchRequest { get; init; }
}
