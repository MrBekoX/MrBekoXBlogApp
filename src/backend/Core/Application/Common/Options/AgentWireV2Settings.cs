namespace BlogApp.Core.Application.Common.Options;

/// <summary>
/// Agent wire v2 üretici anahtarı — appsettings "AgentWireV2" section (K4).
/// Kapalıyken (varsayılan) backend yeni run'ları v1 üretir; <c>who_am_i</c> konusu 503
/// (capability_unavailable) alır. Açıkken ek olarak <see cref="Interfaces.Messaging.IAgentWireV2Readiness"/>
/// bariyeri geçilmelidir (v2 kuyrukları var + en az bir tüketici). Rollback: önce bu anahtar
/// kapatılır (yeni v2 run üretilmez); başlamış v2 run'ları kendi sürümünde biter.
/// </summary>
public sealed class AgentWireV2Settings
{
    public const string SectionName = "AgentWireV2";

    /// <summary>Üretici anahtarı: true iken (ve broker bariyeri hazırken) yeni run'lar v2 üretilir.</summary>
    public bool Enabled { get; set; }

    /// <summary>Hazırlık (readiness) sonucunun önbellek süresi (saniye); K4: 30 sn.</summary>
    public int ReadinessCacheSeconds { get; set; } = 30;
}
