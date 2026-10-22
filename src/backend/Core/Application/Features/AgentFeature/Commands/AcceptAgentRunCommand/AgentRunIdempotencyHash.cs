using System.Security.Cryptography;
using System.Text;
using BlogApp.Core.Application.Features.AgentFeature.Services;

namespace BlogApp.Core.Application.Features.AgentFeature.Commands.AcceptAgentRunCommand;

/// <summary>
/// Kabul idempotency payload özeti (K6). <c>auto</c> konusunda özet konu öncesi tanımla birebir
/// aynıdır (eski kayıtlar auto okunur ve replay'leri bozulmaz); <c>who_am_i</c> için birleştirmeye
/// <c>"\nwho_am_i"</c> eklenir. Böylece aynı anahtar farklı konuyla gelirse özet farklılaşır ve
/// mevcut çakışma (409) semantiği uygulanır — farklı konulu payload replay edilmez (A28).
/// </summary>
public static class AgentRunIdempotencyHash
{
    public static string Compute(AcceptAgentRunCommandRequest request, string normalizedTopic)
    {
        var canonical = string.Join('\n',
            request.Question,
            request.Language,
            request.ModePreference,
            request.BudgetProfile,
            request.ArticleId?.ToString("D") ?? string.Empty,
            request.SelectedText ?? string.Empty);

        if (normalizedTopic == AgentConversationTopics.WhoAmI)
        {
            canonical += "\n" + AgentConversationTopics.WhoAmI;
        }

        return Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(canonical))).ToLowerInvariant();
    }
}
