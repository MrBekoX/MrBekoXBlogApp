"""RouteDecision ve mod yükseltme kaydı.

Router kararı hazırlık girişinde bir kez hesaplanır ve değer olarak taşınır;
plan yürütme ve resume bu kararı yeniden model çağrısıyla hesaplamaz
(plan A1, ``01-agent-gelistirme-plani.md:186``).

A5 alan kümesi (plan A5: "RouteDecision alanları"): ``intent``,
``selected_mode``, ``source_scope``, ``needs_web``, ``needs_clarification``,
``clarification_question``, ``brief_reason``, ``budget_profile_id``.

Donuk taşıma sözleşmesi korunur: B1 ``AgentRunModeSelectedV1`` "web bayrağı
yalnız deep_research'te true olabilir" kuralını zorunlu kılar; ``needs_web``
iş modelinde de aynı değişmezle denetlenir. A1 alan adları (``reason``,
``requires_web_search``) okuma takma adı ve kurucu girdisi olarak kabul
edilmeye devam eder; JSON çıktısı yalnız A5 alan adlarını taşır.
"""

from __future__ import annotations

from pydantic import Field, model_validator

from .base import BusinessModel, Identifier, NonEmptyText, UtcDatetime
from .enums import AgentMode, RunIntent, SourceScope

__all__ = ["ModeUpgradeRecord", "RouteDecision"]


class ModeUpgradeRecord(BusinessModel):
    """Sınırlı mod yükseltmesinin kalıcı kaydı (plan A5: "Mod yükseltmesini
    sınırlı ve kayıtlı yap").

    Yükseltme çalışma başına en fazla bir kez yapılır ve yalnız ``fast →
    analysis`` yönündedir; ``AgentOutcome.mode_upgrades`` ile taşınır.
    """

    from_mode: AgentMode
    to_mode: AgentMode
    reason: NonEmptyText
    upgraded_at: UtcDatetime

    @model_validator(mode="after")
    def _only_fast_to_analysis(self) -> "ModeUpgradeRecord":
        allowed = (AgentMode.FAST, AgentMode.ANALYSIS)
        if self.from_mode not in allowed or self.to_mode not in allowed:
            raise ValueError("mod yükseltmesi yalnız fast → analysis yönünde olabilir")
        ranks = {AgentMode.FAST: 0, AgentMode.ANALYSIS: 1}
        if ranks[self.to_mode] <= ranks[self.from_mode]:
            raise ValueError("mod yükseltmesi çalışma modunu yükseltmelidir (fast → analysis)")
        return self


class RouteDecision(BusinessModel):
    """Bir kez hesaplanmış rota kararı; ``PreparedRun`` içinde serileştirilir.

    ``budget_profile_id`` doğrulanmış politika profilinin kimliğidir: LLM'in
    ürettiği hiçbir limit değeri uygulanmaz (plan A5: "LLM'nin ürettiği
    limitleri doğrudan uygulama; doğrulanmış politika profiline eşle").
    """

    run_id: Identifier
    selected_mode: AgentMode
    #: Plan A5: kararın bağlı olduğu görev türü.
    intent: RunIntent = RunIntent.ARTICLE_QA
    #: Plan A5: çalışmanın planlanan kaynak kapsamı; router set eder.
    source_scope: SourceScope | None = None
    #: Plan A5: güncel dış kanıt gereksinimi; yalnız deep_research'te true olabilir.
    needs_web: bool = False
    #: Plan A5: gerekli bağlam/kişisel bilgi eksikse açık soru ile işaretle;
    #: eksik bilgi tahminle tamamlanmaz.
    needs_clarification: bool = False
    clarification_question: str | None = Field(default=None, max_length=2000)
    brief_reason: NonEmptyText
    budget_profile_id: Identifier | None = None
    decided_at: UtcDatetime

    @model_validator(mode="before")
    @classmethod
    def _accept_legacy_field_names(cls, data: object) -> object:
        """A1 kurucu girdilerini A5 alan adlarına çevirir (geriye dönük uyum).

        ``reason`` → ``brief_reason``; ``requires_web_search`` → ``needs_web``.
        JSON çıktısında yalnız A5 adları vardır; takma adlar serileştirilmez.
        """
        if isinstance(data, dict):
            data = dict(data)
            if "reason" in data and "brief_reason" not in data:
                data["brief_reason"] = data.pop("reason")
            if "requires_web_search" in data and "needs_web" not in data:
                data["needs_web"] = data.pop("requires_web_search")
        return data

    @property
    def reason(self) -> str:
        """A1 okuma takma adı; serileştirilmez."""
        return self.brief_reason

    @property
    def requires_web_search(self) -> bool:
        """A1 okuma takma adı; serileştirilmez."""
        return self.needs_web

    @model_validator(mode="after")
    def _decision_invariants(self) -> "RouteDecision":
        # Donuk taşıma sözleşmesiyle aynı değişmez (B1 AgentRunModeSelectedV1):
        # web bayrağı yalnız derin araştırmada true olabilir.
        if self.selected_mode is not AgentMode.DEEP_RESEARCH and self.needs_web:
            raise ValueError("needs_web yalnız deep_research modunda true olabilir")
        if self.needs_clarification and not (self.clarification_question or "").strip():
            raise ValueError("needs_clarification=true için clarification_question zorunludur")
        if not self.needs_clarification and self.clarification_question is not None:
            raise ValueError("needs_clarification=false iken clarification_question dolu olamaz")
        return self
