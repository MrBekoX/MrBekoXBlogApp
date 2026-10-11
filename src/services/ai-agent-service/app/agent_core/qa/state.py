"""QA akışının LangGraph state sözleşmesi (plan A4).

A2 ortak ``AgentState``'in makale soru-cevap karşılığıdır: alan kümesi
akışın altı node sorumluluğuna aittir, liste kanalları reducer'lıdır ve
tek döngüde (retrieve → evaluate) çalışır. Checkpoint-dışı büyük metin
yoktur: bölüm kayıtları ``ChunkingConfig`` ile sınırlı uzunluktadır ve
state'te taşınabilir.

Seriye atma A8 checkpoint katmanının kapsamıdır; bu aşama graph içi
yaşam süresiyle sınırlıdır.
"""

from __future__ import annotations

from typing import Annotated, TypedDict

from ..content.models import IndexedChunk
from ..models import (
    AgentOutcome,
    ArticleSnapshot,
    ConversationTurn,
    ExecutionContext,
    RouteDecision,
    SourceReference,
)
from ..state.events import NodeErrorRecord, UsageEvent
from ..state.state import merge_error_records, merge_messages, merge_usage_events
from .models import QaSectionRef, SufficiencyVerdict

__all__ = ["QaState", "chunk_key", "merge_chunks"]


def chunk_key(record: IndexedChunk) -> tuple[str, int, int]:
    """Bölüm kimliği: (article_id, article_revision, chunk_index) — A0 §7.3."""
    return (record.article_id, record.article_revision, record.chunk_index)


def merge_chunks(left: list[IndexedChunk], right: list[IndexedChunk]) -> list[IndexedChunk]:
    """Getirilen bölümleri kimlikle birleştirir; tekrar aramada kopya düşer.

    İlk aramanın zayıf bölümleri listede kalır: yeterlilik değerlendirmesi
    birleşik küme üzerinde yapılır, böylece düzenlenmiş sorgunun yeni
    getirdiği bölüm kararı belirler.
    """
    merged = list(left)
    seen = {chunk_key(record) for record in merged}
    for record in right:
        key = chunk_key(record)
        if key not in seen:
            seen.add(key)
            merged.append(record)
    return merged


class QaState(TypedDict, total=False):
    """Makale soru-cevap akışının state'i; tüm alanlar graph içi seriyadır."""

    run_id: str

    #: Girdi bağlamı ve hazırlıkta hesaplanmış rota kararı (A1 sözleşmesi).
    context: ExecutionContext
    route: RouteDecision | None

    #: Bağlam doğrulamasının çıktıları.
    snapshot: ArticleSnapshot | None
    article_revision: int | None
    selected_text_ok: bool | None

    #: Retrieval döngüsü: sorgu, deneme sayısı ve düzenleme bayrağı.
    retrieval_query: str
    retrieval_attempt: int
    rewritten: bool
    retrieved: Annotated[list[IndexedChunk], merge_chunks]

    #: Yeterlilik kararı ve üretim.
    sufficiency: SufficiencyVerdict | None
    draft_answer: str | None

    #: Kaynak ve kapsam kontrolünün çıktıları.
    answer: str | None
    citations: list[SourceReference]
    sections: list[QaSectionRef]

    #: Terminal sonuç ve koleksiyon kanalları.
    outcome: AgentOutcome | None
    messages: Annotated[list[ConversationTurn], merge_messages]
    usage_events: Annotated[list[UsageEvent], merge_usage_events]
    errors: Annotated[list[NodeErrorRecord], merge_error_records]
