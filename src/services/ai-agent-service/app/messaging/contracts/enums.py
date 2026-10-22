"""Transport sözleşmesi enum'ları.

Değerler A1 iş modeli enum'larıyla (``agent_core.models.enums``) birebir aynıdır;
burada ayrı tanımlanmaları transport katmanının ``agent_core``'a bağımlılık
taşımaması içindir. Denklik ``tests/test_messaging_contracts_rules.py``
içindeki eşleme testiyle sabitlenir.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = [
    "AgentErrorCode",
    "AgentMode",
    "ConversationTopic",
    "Direction",
    "ModePreference",
    "Producer",
    "ProgressKind",
    "RunIntent",
    "SourceScope",
]


class Producer(StrEnum):
    """Envelope.producer değerleri (B0 §4 üç katmanlı işaretleme)."""

    BACKEND_NET = "backend-net"
    AGENT_PY = "agent-py"
    TEST_EXECUTOR = "test-executor"


class Direction(StrEnum):
    """Mesaj yönü; contract.json 'direction' değerleriyle aynı biçimdedir."""

    BACKEND_TO_AGENT = "backend_to_agent"
    AGENT_TO_BACKEND = "agent_to_backend"


class AgentMode(StrEnum):
    """Kesinleşmiş çalışma modu; 'auto' burada yer almaz."""

    FAST = "fast"
    ANALYSIS = "analysis"
    DEEP_RESEARCH = "deep_research"


class ModePreference(StrEnum):
    """Kullanıcının mod tercihi."""

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


class AgentErrorCode(StrEnum):
    """Ortak hata kodları (W0 §1.5); AgentRunFailedV1.payload.error_code taşır."""

    CONFIG_ERROR = "config_error"
    VALIDATION_ERROR = "validation_error"
    NOT_FOUND = "not_found"
    STALE_SNAPSHOT = "stale_snapshot"
    BUDGET_EXHAUSTED = "budget_exhausted"
    CANCELLED = "cancelled"
    PROVIDER_ERROR = "provider_error"
    TIMEOUT = "timeout"


class ProgressKind(StrEnum):
    """DomainProgress olay türleri (A1 ile aynı kapalı küme).

    ``GENERATION_DELTA`` (additive): LLM parçalı metin chunk'ı; seyrekleştirilmez,
    chunk 1500 karakteri aşmaz (bölünmüş chunk).
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


class ConversationTopic(StrEnum):
    """v2 sohbet konusu (``conversation_topic``); A1 ``ConversationTopic`` ile aynı küme.

    Çalışma derinliğinden (``ModePreference``) bağımsızdır; v1 sözleşmesinde yoktur.
    """

    AUTO = "auto"
    WHO_AM_I = "who_am_i"


class RunIntent(StrEnum):
    """v2 etkin niyet (``run_intent``); A1 ``RunIntent`` ile aynı kapalı küme.

    Routing'in çözdüğü niyet, istenen konudan (``ConversationTopic``) ayrı taşınır;
    ``profile`` niyeti profil kapsamı, web'siz çalışma ve pinlenmiş snapshot ister.
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
