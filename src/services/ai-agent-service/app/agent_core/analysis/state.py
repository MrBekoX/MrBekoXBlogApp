"""Analysis alt akışının LangGraph state sözleşmesi (plan A5).

A4 ``QaState`` reducer desenini izler: liste kanalları kimlikle birleşir,
kopya arama/tekrar yürütme kopya kullanım üretmez. ``plan`` başlıkları,
``coverage`` kanıt kontrolünü, ``scope_expanded`` kapsam artırma turunun
yapıldığını taşır; ``mode_upgrade`` sınırlı mod yükseltmesinin kaydını
tutarak terminal sonuca yansır (plan A5: kayıtlı yükseltme).
"""

from __future__ import annotations

from typing import Annotated, TypedDict

from ..content.models import IndexedChunk
from ..models import (
    AgentOutcome,
    ArticleSnapshot,
    ConversationTurn,
    ExecutionContext,
    ModeUpgradeRecord,
    RouteDecision,
    SourceReference,
)
from ..qa.models import QaSectionRef
from ..qa.state import merge_chunks
from ..state.events import NodeErrorRecord, UsageEvent
from ..state.state import merge_error_records, merge_messages, merge_usage_events
from .models import AnalysisPlan, HeadingCoverage

__all__ = ["AnalysisState"]


class AnalysisState(TypedDict, total=False):
    """Analysis akışının state'i; tüm alanlar graph içi seriyadır."""

    run_id: str

    #: Girdi bağlamı ve hazırlıkta hesaplanmış rota kararı (A1 sözleşmesi).
    context: ExecutionContext
    route: RouteDecision | None

    #: Sorudan ayrıştırılan cevap başlıkları (plan A5).
    plan: AnalysisPlan | None

    #: Bağlam doğrulamasının çıktıları (A4 validate düğümüyle aynı anahtarlar).
    snapshot: ArticleSnapshot | None
    article_revision: int | None
    selected_text_ok: bool | None

    #: Retrieval: birleşik sonuçlar ve kapsam artırma bayrağı.
    retrieved: Annotated[list[IndexedChunk], merge_chunks]
    scope_expanded: bool

    #: Kanıt kontrolü ve üretim.
    coverage: HeadingCoverage | None
    draft_answer: str | None

    #: Kaynak ve kapsam kontrolünün çıktıları.
    answer: str | None
    citations: list[SourceReference]
    sections: list[QaSectionRef]

    #: Sınırlı mod yükseltmesi kaydı (fast → analysis); en fazla bir kayıt.
    mode_upgrade: ModeUpgradeRecord | None

    #: Terminal sonuç ve koleksiyon kanalları.
    outcome: AgentOutcome | None
    messages: Annotated[list[ConversationTurn], merge_messages]
    usage_events: Annotated[list[UsageEvent], merge_usage_events]
    errors: Annotated[list[NodeErrorRecord], merge_error_records]
