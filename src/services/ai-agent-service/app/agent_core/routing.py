"""Mod yönlendirme: saf, deterministik fonksiyon — model çağrısı yapmaz.

Plan A1 kuralı: "Aynı router kararının yeniden model çağrısıyla hesaplanmasını
önle" (``01-agent-gelistirme-plani.md:186``). Karar hazırlık girişinde bir kez
hesaplanır ve ``RouteDecision`` değeri olarak taşınır; ``execute_plan`` ve
``resume`` bu modülü çağırmaz. Yönlendirme akışı girdiyi sınıflandırıp uygun
göreve gönderir [LG-WORKFLOWS#C1]; A2'de graph içi zenginleştirme bu modülü
kullanmaya devam edebilir.
"""

from __future__ import annotations

from datetime import datetime, timezone

from .models import AgentMode, ExecutionContext, ModePreference, RouteDecision

__all__ = ["decide_mode", "route_for_context"]

#: Soru uzunluğu bu eşiği aşarsa soru çok parçalı sayılır ve araştırmaya yönlendirilir.
DEEP_RESEARCH_QUESTION_THRESHOLD = 240

#: Derin araştırma gerektiren konu sinyalleri (tr/en). Alt dizin eşleşmesi,
#: küçük harfe katlanmış soru üzerinde yapılır.
_RESEARCH_SIGNALS = (
    "araştır", "incele", "karşılaştır", "derin", "rapor hazırla", "güncel durumu",
    "trend", "trends", "research", "compare", "deep dive", "state of", "literature",
    " latest", "en yeni",
)

#: Açıklama/kod analizi sinyalleri: seçili metin varsa veya soru açıklama isterse.
_ANALYSIS_SIGNALS = (
    "açıkla", "nasıl çalışır", "kod", "ne yapıyor", "explain", "how does",
    "what does", "walk through", "review",
)


def decide_mode(question: str, *, has_selection: bool, preference: ModePreference) -> AgentMode:
    """Deterministik mod kararı; ModelProvider kullanmaz.

    Sıra: açık tercih → seçili metin (analysis) → araştırma sinyali veya uzun
    soru (deep_research) → açıklama sinyali (analysis) → fast.
    """
    if preference is not ModePreference.AUTO:
        return AgentMode(preference.value)

    folded = question.casefold()
    if has_selection:
        return AgentMode.ANALYSIS
    if any(signal in folded for signal in _RESEARCH_SIGNALS):
        return AgentMode.DEEP_RESEARCH
    if len(question) > DEEP_RESEARCH_QUESTION_THRESHOLD:
        return AgentMode.DEEP_RESEARCH
    if any(signal in folded for signal in _ANALYSIS_SIGNALS):
        return AgentMode.ANALYSIS
    return AgentMode.FAST


def route_for_context(context: ExecutionContext) -> RouteDecision:
    """ExecutionContext'ten bir kez ``RouteDecision`` üretir."""
    mode = decide_mode(
        context.question,
        has_selection=context.selected_text is not None,
        preference=context.mode_preference,
    )
    reason = f"kullanıcı tercihi: {context.mode_preference.value}" if (
        context.mode_preference is not ModePreference.AUTO
    ) else "auto sezgisi: " + (
        "seçili metin açıklaması" if mode is AgentMode.ANALYSIS
        else "araştırma sinyali/uzun soru" if mode is AgentMode.DEEP_RESEARCH
        else "kısa ve tekil soru"
    )
    return RouteDecision(
        run_id=context.run_id,
        selected_mode=mode,
        reason=reason,
        requires_web_search=mode is AgentMode.DEEP_RESEARCH,
        decided_at=datetime.now(timezone.utc),
    )
