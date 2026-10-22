"""İş modeli enum'ları.

``RunStatus`` yalnız beş terminal/iş değeri taşır; "kuyruğa alındı", "teslim
edildi" gibi broker/teslim durumları iş modeli durumu değildir (plan A1,
``01-agent-gelistirme-plani.md:182``; W0 §1.3).
"""

from __future__ import annotations

from enum import StrEnum

__all__ = ["AgentMode", "ConversationTopic", "ModePreference", "ProgressKind", "RunIntent", "RunStatus", "SourceScope"]


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

    A9 additive üyeler (plan A9: "Profil, proje, içerik önerisi ve iş
    birliği niyetlerini router'a bağla"): ``PROFILE`` profil tanıtımı,
    ``PROJECTS`` proje rehberi, ``CONTENT_SUGGESTION`` ilgiye göre makale
    önerisi, ``COLLABORATION`` iş birliği hazırlığı. Bu niyetler onaylı
    kayıtlardan deterministik akışlarla yürütülür; makale retrieval'sızdır.
    """

    ARTICLE_QA = "article_qa"
    SUMMARIZE = "summarize"
    EXPLAIN = "explain"
    COMPARE = "compare"
    RESEARCH = "research"
    GENERAL = "general"
    PROFILE = "profile"
    PROJECTS = "projects"
    CONTENT_SUGGESTION = "content_suggestion"
    COLLABORATION = "collaboration"


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


class ConversationTopic(StrEnum):
    """Kullanıcının seçtiği sohbet konusu (v2 sözleşmesi ``conversation_topic``).

    Çalışma derinliğinden (``ModePreference``) bağımsızdır. ``WHO_AM_I`` blog
    sahibi Berkay Kaplan'ın onaylı public profilini konu alır; ziyaretçinin
    kimliğini değil. ``AUTO`` routing'e bırakılır. v1 run'larında konu yoktur
    (``ExecutionContext.conversation_topic is None``).
    """

    AUTO = "auto"
    WHO_AM_I = "who_am_i"


class SourceScope(StrEnum):
    """Sonucun dayandığı kaynak kapsamı."""

    ARTICLE = "article"
    WEB = "web"
    ARTICLE_AND_WEB = "article_and_web"
    PROFILE = "profile"
    PROJECTS = "projects"
    GENERAL = "general"


class ProgressKind(StrEnum):
    """DomainProgress olay türleri; transport monoton event_sequence ekler (W0 Ç6).

    ``TOOL_ERROR`` (additive): web arama/okuma gibi dış araç çağrılarının
    node içinde yakalanan tekil hata izidir; akış kısmi yolda sürer ve
    terminal durumu belirlemez.

    ``GENERATION_DELTA`` (additive): LLM cevabı üretilirken parçalı metin
    taşıyan birleştirilmiş chunk. Token-başına broker mesajı YASAKTIR (events.py
    sözleşmesi); chunk'lar birleştirilmiş olarak akar ve seyrekleştirilmez.
    """

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
    TOOL_ERROR = "tool_error"
    GENERATION_DELTA = "generation_delta"
