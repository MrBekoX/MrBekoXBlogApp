using System.Security.Cryptography;
using System.Text;

namespace BlogApp.Core.Application.Features.AgentFeature.Collaboration;

/// <summary>
/// İş birliği içerik sürümü hash'i (B9) — TEK TANIM (W6 F5): backend'in sakladığı
/// ve ziyaretçiye gösterdiği düzenlenebilir özet metninin UTF-8 SHA-256 özeti
/// (lowercase hex; D008 hash anlamıyla aynı kural). A9 üreticisi de
/// proposal_content_hash'i AYNI metnin AYNI özeti olarak üretir
/// (agent_core/collab/proposal.py: compute_content_hash(proposal.summary));
/// iki taraf aynı özet için aynı hash'i üretir ve sürüm bağı kabloyla uyuşur.
/// Onay isteği bu sürüm hash'ine karşı doğrulanır; uyuşmazlık "değiştirilmiş
/// proposal" reddidir (plan B9).
/// </summary>
public static class AgentCollaborationContentHash
{
    public static string Compute(string content) =>
        Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(content)));
}
