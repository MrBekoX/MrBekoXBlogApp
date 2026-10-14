namespace BlogApp.Core.Application.Common.Options;

/// <summary>
/// Agent servis kimliği ayarları — appsettings "AgentService" section.
/// <see cref="InternalApiKey"/>: Python agent servisinin backend internal uçlarına
/// (GET /api/v1/agent/internal/content/{articleId}) erişimi için servis anahtarı
/// (X-Agent-Service-Key header'ı). Boş/tanımsızsa internal uç her istek için 404
/// döner (yüzey sızdırma); anahtar yapılandırıldığında karşılaştırma sabit
/// zamanlıdır (CryptographicOperations.FixedTimeEquals).
/// </summary>
public sealed class AgentServiceSettings
{
    public const string SectionName = "AgentService";

    /// <summary>Internal uçlara erişim servis anahtarı; boş = internal yüzey kapalı.</summary>
    public string? InternalApiKey { get; set; }
}
