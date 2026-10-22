using BlogApp.Core.Application.Features.AgentFeature.Services;

namespace BlogApp.Core.Application.Common.Messaging;

/// <summary>
/// Olay ↔ run bağlamı tutarlılığının saf kuralları (K4/K6). Şema doğrulayıcısı yalnız mesajın
/// kendisini görür; bu kurallar kabulde kalıcılaştırılan run bağlamıyla karşılaştırır:
/// <list type="bullet">
/// <item>Olayın schema_version'ı run'ın wire sürümüne eşit olmalıdır (v1 run'a v2 olay veya tersi
///   protokol karışmasıdır).</item>
/// <item>who_am_i run'ı needs_input veya action.proposed üretemez.</item>
/// <item>v2 mode_selected/completed/partially_completed/failed: who_am_i run'ında run_intent (varsa)
///   profile olmalıdır; olay profile_snapshot taşıyorsa kabulde pinlenen snapshot'a eşit olmalıdır
///   (worker başka sürüme sessizce geçemez); run_intent=profile olan içerikli olay snapshot taşımalıdır.</item>
/// </list>
/// İhlal null olmayan bir gerekçe döndürür; projection olayı UYGULAMAZ (bkz. handler).
/// </summary>
public static class AgentRunEventWireRules
{
    public const int MaxReasonLength = 512;

    public static string? Verify(
        AgentRunWireContext context,
        int envelopeSchemaVersion,
        string messageType,
        string? runIntent,
        AgentProfileSnapshotRef? profileSnapshot)
    {
        if (envelopeSchemaVersion != context.WireVersion)
        {
            return $"olay sözleşme sürümü v{envelopeSchemaVersion}, run wire sürümü v{context.WireVersion} ile uyuşmuyor";
        }

        if (!context.IsV2)
        {
            return null;
        }

        // who_am_i askıda iş (needs_input) veya içerik önerisi (action.proposed) üretmez (K1/K5:
        // bilinmeyen/özel bilgi completed yetersiz-bilgi cevabıdır; profil sonucu action_proposal taşımaz).
        if (context.IsWhoAmI && messageType is AgentMessageTypes.RunNeedsInput or AgentMessageTypes.ActionProposed)
        {
            return $"who_am_i run'ı {messageType} üretemez";
        }

        var carriesRouting = messageType is AgentMessageTypes.RunModeSelected
            or AgentMessageTypes.RunCompleted
            or AgentMessageTypes.RunPartiallyCompleted
            or AgentMessageTypes.RunFailed;
        if (!carriesRouting)
        {
            return null;
        }

        if (context.IsWhoAmI)
        {
            if (runIntent is null && messageType != AgentMessageTypes.RunFailed)
            {
                return "who_am_i run'ı etkin niyet (run_intent) taşımayan sonuç üretemez";
            }

            if (runIntent is not null && runIntent != "profile")
            {
                return $"who_am_i run'ı profile dışı etkin niyetle ({runIntent}) yürütülemez";
            }
        }

        if (profileSnapshot is not null && !profileSnapshot.SameAs(context.PinnedProfile))
        {
            return context.PinnedProfile is null
                ? "olay profile_snapshot taşıyor ama run için profil sürümü pinlenmedi"
                : "olayın profile_snapshot'ı kabulde pinlenen profil sürümüyle uyuşmuyor";
        }

        if (runIntent == "profile" && profileSnapshot is null && messageType != AgentMessageTypes.RunFailed)
        {
            return "run_intent=profile olayı pinlenmiş profile_snapshot taşımalıdır";
        }

        return null;
    }
}
