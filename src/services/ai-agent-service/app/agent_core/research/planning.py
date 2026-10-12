"""Makale iddiası çıkarma ve araştırma planı üretimi (plan A7 adım 2-3).

Deterministiktir: model çağrısı yapmaz. İddia = kod blokları ve başlıklar
dışındaki cümle; soruyla terim ilgisi A3/A4 ile aynı ``fold_text`` +
``salient_tokens`` normalizasyonuyla ölçülür [ENG-CONTEXT#C1]. Soru belirli
terim taşımıyorsa (genel soru sınıfı) belgenin kendi cümleleri iddia adayı
olur. Alt sorular sorudan ve ilk iddialardan sınırlı sayıda üretilir
(``BudgetPolicy.max_sub_questions``, politika üst sınırı runner'da uygulanır).
"""

from __future__ import annotations

import re

from ..content.anchors import fold_text
from ..errors import AgentErrorCode, PortError
from ..models import ArticleSnapshot
from ..qa.text import is_generic_question, salient_tokens
from .models import ClaimRecord, ResearchFlowConfig

__all__ = ["build_sub_questions", "extract_claims", "iter_sentences"]

#: Cümle bölücü: satır sonu veya noktalama ile biter; önündeki boşluk yakalanır.
_SENTENCE_RE = re.compile(r"\s*([^.!?\n]+[.!?]*)")

#: Kod blokları ve markdown başlıkları iddia değildir.
_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
_HEADING_RE = re.compile(r"(?m)^[ \t]*#{1,6}[^\n]*$")

_MIN_CLAIM_CHARS = 24


def iter_sentences(text: str) -> list[tuple[int, int, str]]:
    """Metni ofsetli cümlelere ayırır; kod bloğu ve başlık aralıklarını atlar.

    Dönen aralıklar orijinal metnin UTF-16-bağımsız Python karakter
    indeksleridir; kanıt ``char_start/char_end`` bu uzaydadır.
    """
    excluded: list[tuple[int, int]] = [
        (m.start(), m.end()) for m in _FENCE_RE.finditer(text)
    ] + [(m.start(), m.end()) for m in _HEADING_RE.finditer(text)]

    def excluded_overlap(start: int, end: int) -> bool:
        return any(start < b and end > a for a, b in excluded)

    sentences: list[tuple[int, int, str]] = []
    for match in _SENTENCE_RE.finditer(text):
        raw = match.group(1)
        stripped = raw.strip()
        if len(stripped) < _MIN_CLAIM_CHARS:
            continue
        lead = len(raw) - len(raw.lstrip())
        char_start = match.start(1) + lead
        char_end = char_start + len(stripped)
        if excluded_overlap(char_start, char_end):
            continue
        sentences.append((char_start, char_end, stripped))
    return sentences


def extract_claims(
    snapshot: ArticleSnapshot,
    question: str,
    *,
    config: ResearchFlowConfig | None = None,
) -> list[ClaimRecord]:
    """Makaleden soruyla ilgili iddiaları çıkarır; sayaç ve aralık sınırlıdır.

    Soru genel sınıftaysa veya hiç cümle soru terimi taşımıyorsa belgenin
    ilk cümleleri iddia olur (sıfır iddia planı boşa düşürür; plan adımı
    ``validation_error`` üretir).
    """
    flow_config = config or ResearchFlowConfig()
    question_tokens = set(salient_tokens(fold_text(question), min_length=3))
    generic = is_generic_question(question)

    scored: list[tuple[int, int, int, str]] = []
    for char_start, char_end, text in iter_sentences(snapshot.content):
        tokens = set(salient_tokens(fold_text(text), min_length=3))
        overlap = len(question_tokens & tokens)
        scored.append((overlap, char_start, char_end, text))

    if not generic:
        relevant = [item for item in scored if item[0] >= flow_config.min_claim_overlap]
    else:
        relevant = []
    chosen = relevant or scored
    # Belge sırası korunur; en uzun cümleler önce eleme (kısa parçalar iddia taşımaz).
    chosen = [item for item in chosen if len(item[3]) >= _MIN_CLAIM_CHARS][: flow_config.max_claims]

    claims: list[ClaimRecord] = []
    for index, (_, char_start, char_end, text) in enumerate(chosen):
        claims.append(
            ClaimRecord(
                claim_id=f"claim:{snapshot.article_id}:{snapshot.article_revision}:{index}",
                article_id=snapshot.article_id,
                article_revision=snapshot.article_revision,
                text=text[:2000],
                char_start=char_start,
                char_end=char_end,
            )
        )
    return claims


def build_sub_questions(
    question: str,
    claims: list[ClaimRecord],
    *,
    max_sub_questions: int,
    language: str,
) -> list[str]:
    """Araştırma alt sorularını üretir: soru + iddia doğrulama soruları (sınırlı).

    Plan A7: "ResearchPlan ve sınırlı alt sorular üret" — üst sınır politika
    ``max_sub_questions`` (varsayılan 4); ilk soru kullanıcının sorusudur.
    """
    if not claims:
        raise PortError(
            AgentErrorCode.VALIDATION_ERROR,
            "araştırma kapsamı boş: makalede soruyla ilgili iddia çıkarılamadı",
            port="research.plan",
        )
    questions = [question.strip()]
    is_tr = language.casefold().startswith("tr")
    for claim in claims[: max(max_sub_questions - 1, 0)]:
        if is_tr:
            questions.append(f"Makaledeki şu iddia güncel kaynaklarla uyumlu mu: {claim.text}")
        else:
            questions.append(
                f"Is this article claim consistent with current sources: {claim.text}"
            )
    return questions[:max_sub_questions]
