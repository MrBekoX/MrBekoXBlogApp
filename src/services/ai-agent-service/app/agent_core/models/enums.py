"""İş modeli enum'ları.

``RunStatus`` yalnız beş terminal/iş değeri taşır; "kuyruğa alındı", "teslim
edildi" gibi broker/teslim durumları iş modeli durumu değildir (plan A1,
``01-agent-gelistirme-plani.md:182``; W0 §1.3).
"""

from __future__ import annotations

from enum import StrEnum

__all__ = ["AgentMode", "ModePreference", "ProgressKind", "RunIntent", "RunStatus", "SourceScope"]


class RunStatus(StrEnum):
    """AgentOutcome durumları: yalnız iş sonucu, teslim durumu değil."""

    COMPLETED = "completed"
    PARTIAL = "partial"
    NEEDS_INPUT = "needs_input"
    CANCELLED = "cancelled"
    FAILED = "failed"


class RunIntent(StrEnum):
    """Router'ın sınıflandırdığı görev türü (plan A5 ``RouteDecision.intent``).

    ``RESEARCH`` güncellik/dış kanıt dahil araştırma görevidir; ``COMPARE``
    karşılaştırma veya senaryoya uyarlama, ``EXPLAIN`` seçili metin/kod
    açıklaması, ``SUMMARIZE`` makaleyi bütün olarak soran özet sınıfıdır.
    """

    ARTICLE_QA = "article_qa"
    SUMMARIZE = "summarize"
    EXPLAIN = "explain"
    COMPARE = "compare"
    RESEARCH = "research"
    GENERAL = "general"


class AgentMode(StrEnum):
    """Kesinleşmiş çalışma modu; ``auto`` burada yer almaz (karar verilmiş olmalı)."""

    FAST = "fast"
    ANALYSIS = "analysis"
    DEEP_RESEARCH = "deep_research"


class ModePreference(StrEnum):
    """Kullanıcının mod tercihi; ``auto`` routing'e bırakılır."""

    AUTO = "auto"
    FAST = "fast"
    ANALYSIS = "analysis"
    DEEP_RESEARCH = "deep_research"


class SourceScope(StrEnum):
    """Sonucun dayandığı kaynak kapsamı."""

    ARTICLE = "article"
    WEB = "web"
    ARTICLE_AND_WEB = "article_and_web"
    PROFILE = "profile"
    PROJECTS = "projects"
    GENERAL = "general"


class ProgressKind(StrEnum):
    """DomainProgress olay türleri; transport monoton event_sequence ekler (W0 Ç6)."""

    RUN_STARTED = "run_started"
    MODE_SELECTED = "mode_selected"
    ARTICLE_CONTEXT_READY = "article_context_ready"
    RUN_RESUMED = "run_resumed"
    RETRIEVAL_STARTED = "retrieval_started"
    RETRIEVAL_COMPLETED = "retrieval_completed"
    RESEARCH_STARTED = "research_started"
    RESEARCH_ROUND_COMPLETED = "research_round_completed"
    GENERATION_STARTED = "generation_started"
    GENERATION_COMPLETED = "generation_completed"
    VALIDATION_COMPLETED = "validation_completed"
    ACTION_PROPOSED = "action_proposed"
