"""Yeterlilik değerlendirmesi (plan A4 node sorumluluğu).

Retrieval sonrasında getirilen bölümlerin soruyla ilgisi değerlendirilir;
ilgisiz sonuçlarda sorgu bir kez düzenlenip arama tekrarlanır, yine
yetersizse yetersiz bilgi yanıtı verilir [LG-RAG#C1].

Karar deterministiktir: soru terimlerinin bölüm içeriğiyle örtüşmesi.
Gerçek model tabanlı değerlendirme (Self-RAG tarzı yansımalı derecelendirme
[AC-SELF-RAG#C1]) sağlayıcı devreye girdiğinde bu modülün yerine geçer;
arayüz buradaki imzadır.
"""

from __future__ import annotations

from ..content.anchors import fold_text
from ..content.retrieval import tokenize
from ..content.models import IndexedChunk
from .models import SufficiencyVerdict
from .text import is_generic_question, salient_tokens

__all__ = ["evaluate_sufficiency"]

#: Belirli sorularda bölümü kanıt saymak için gereken en az ortak terim.
MIN_MATCHED_TOKENS = 1


def evaluate_sufficiency(question: str, retrieved: list[IndexedChunk]) -> SufficiencyVerdict:
    """Getirilen bölümler soruyu karşılamaya yeterli mi?

    - Genel sorular (ana fikir/özet sınıfı): makaleyi bütün olarak sorduğu
      için getirilen her bölüm kanıt sayılır; hiç bölüm gelmediyse yetersiz.
    - Belirli sorular: en az bir bölüm sorunun anlamlı terimlerinden
      ``MIN_MATCHED_TOKENS`` adedini taşıyorsa yeterli.
    - Hiçbiri yoksa yetersiz; koşullu kenar sorgu düzenleme kararı verir.
    """

    generic = is_generic_question(question)
    if generic:
        matched = [record.chunk_index for record in retrieved]
        if retrieved:
            return SufficiencyVerdict(
                sufficient=True,
                reason="makaleyi bütün olarak soran genel soru; getirilen bölümler kanıt",
                generic_question=True,
                matched_chunk_indexes=matched,
            )
        return SufficiencyVerdict(
            sufficient=False,
            reason="genel soru ama makaleden hiç bölüm getirilemedi",
            generic_question=True,
            matched_chunk_indexes=[],
        )

    question_tokens = set(salient_tokens(question, min_length=3))
    matched = []
    for record in retrieved:
        evidence_tokens = set(tokenize(fold_text(record.chunk.content)))
        overlap = sum(1 for token in question_tokens if token in evidence_tokens)
        if overlap >= MIN_MATCHED_TOKENS:
            matched.append(record.chunk_index)
    if matched:
        return SufficiencyVerdict(
            sufficient=True,
            reason=f"{len(matched)} bölüm soru terimlerini taşıyor",
            matched_chunk_indexes=matched,
        )
    return SufficiencyVerdict(
        sufficient=False,
        reason="getirilen bölümlerde sorunun terimlerine rastlanmadı",
        matched_chunk_indexes=[],
    )
