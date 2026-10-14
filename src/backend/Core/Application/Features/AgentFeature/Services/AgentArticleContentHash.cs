using System.Security.Cryptography;
using System.Text;

namespace BlogApp.Core.Application.Features.AgentFeature.Services;

/// <summary>
/// Makale içerik hash'i — TEK TANIM (W6 F5 deseninin makale karşılığı): kabul
/// anındaki <c>AgentRun.ArticleContentHash</c> (AcceptAgentRunCommandHandler.
/// BuildContextSnapshot) ve agent internal content endpoint'inin <c>contentHash</c>
/// alanı (GetAgentInternalContentQueryHandler) AYNI fonksiyondan üretilir.
/// İçerik markdown'ının UTF-8 SHA-256 özeti, lowercase hex (D008). Python tarafı
/// da AYNI özeti üretir (agent_core/models/article.py: compute_content_hash =
/// sha256(utf-8).hexdigest()); üç taraf aynı içerik için aynı hash'i verir ve
/// worker stale_snapshot guard'ı yanlışlıkla tetiklenmez.
/// </summary>
public static class AgentArticleContentHash
{
    public static string Compute(string content) =>
        Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(content)));
}
