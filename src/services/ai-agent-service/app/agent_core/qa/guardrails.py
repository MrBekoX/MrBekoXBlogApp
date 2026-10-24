"""Kaynak ve kapsam kontrolü (plan A4 node sorumluluğu).

Model çıktısı terminal cevaba dönüştürülürken üç denetim uygulanır:

1. **Kaynak seçimi:** Atıflar yalnız gerçekten getirilen kanıt kayıtlarından
   seçilir; cevap metniyle en az ``min_overlap`` anlamlı terimi paylaşan
   bölümler atıf olur. Getirilmemiş hiçbir kimlik atıf olamaz (plan A4:
   "Kaynak ID'lerini gerçekten getirilen kanıtlardan seç").
2. **Atıf denetimi:** "Makaleye göre / yazara göre" kalıbıyla yapılmış ama
   kanıt metniyle desteklenmeyen cümle cevaptan tümüyle çıkarılır; makalede
   bulunmayan görüş yazara/makaleye atfedilmez (plan A4). Desteklenen
   atıflar aynen kalır. Cevap dili bağlam verisi değildir; kaynak metindeki
   talimatlar bu denetimi değiştiremez [LG-RAG#C2].
3. **Bölüm bağlantıları:** Atıf yapılan bölümler için bağlantılar indeks
   kaydının canonical URL'sinden üretilir (plan A4: "Bölüm bağlantılarını
   doğrulanmış makale URL'sinden üret").
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from ..content.anchors import fold_text
from ..content.models import IndexedChunk
from ..models import SourceReference
from .models import QaSectionRef
from .text import salient_tokens

__all__ = [
    "ATTRIBUTION_SUPPORT_MIN_TOKENS",
    "append_source_block",
    "build_citations",
    "build_section_refs",
    "ground_answer",
    "neutralize_attributions",
    "select_citations",
    "split_sentences",
]

#: Atıf kalıpları; katlanmış metinde alt dizin olarak aranır (tr/en).
_ATTRIBUTION_MARKERS = (
    "makaleye göre",
    "yazara göre",
    "makalede belirtildiği gibi",
    "makaleye atfen",
    "according to the article",
    "according to the author",
    "the article states",
    "the article says",
    "the author claims",
    "the author says",
)

#: Atfı çıkarılan cümle için kanıt desteği eşiği (anlamlı terim adedi).
ATTRIBUTION_SUPPORT_MIN_TOKENS = 2

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?…])\s+")
_NUMBER_RE = re.compile(r"(?<!\w)[+-]?\d+(?:[.,]\d+)?(?!\w)")
_NEGATION_RE = re.compile(
    r"\b(?:not|no|never|without|cannot|isn't|aren't|doesn't|don't|won't|"
    r"degil\w*|asla|olmaz|olmamal[iı]\w*|onerilmez|desteklenmez|gerekmez|"
    r"kullanmay[iı]n|yapmay[iı]n)\b", re.IGNORECASE,
)
_INLINE_IDENTIFIER_RE = re.compile(r"`([^`\n]+)`")
_CODE_IDENTIFIER_RE = re.compile(
    r"\b(?:[A-Z][a-z]+(?:[A-Z][A-Za-z0-9]*)+|[a-z]+(?:[A-Z][A-Za-z0-9]*)+|[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9_]+)\b"
)
_SOURCE_LABEL_RE = re.compile(r"\[(?:article|web|profile):[^\]]+\]")
_FENCE_RE = re.compile(r"(^[ \t]*(`{3,}|~{3,})[^\n]*\n.*?^[ \t]*\2[ \t]*$)", re.M | re.S)


def _numbers(text: str) -> list[Decimal]:
    values: list[Decimal] = []
    for value in _NUMBER_RE.findall(text):
        try:
            values.append(Decimal(value.replace(",", ".")))
        except InvalidOperation:  # bounded inputs, defensive against malformed numbers
            continue
    return values


def _consistent_claim(claim: str, evidence: str, *, min_tokens: int) -> bool:
    """Conservative local support check, not a proof of semantic entailment.

    Numbers, negation and literal code identifiers must agree within the same
    evidence span. A number elsewhere in the article cannot justify a claim.
    """
    claim = _SOURCE_LABEL_RE.sub("", claim)
    claim_tokens = set(salient_tokens(claim, min_length=4))
    evidence_tokens = set(salient_tokens(evidence, min_length=4))
    if len(claim_tokens & evidence_tokens) < min_tokens:
        return False
    evidence_numbers = iter(_numbers(evidence))
    for number in _numbers(claim):
        # Order matters: a reversed range must not be supported by the same set
        # of numbers. Additional source values may be omitted in a short answer.
        if not any(number == candidate for candidate in evidence_numbers):
            return False
    if bool(_NEGATION_RE.search(fold_text(claim))) != bool(_NEGATION_RE.search(fold_text(evidence))):
        return False
    identifiers = _INLINE_IDENTIFIER_RE.findall(claim) + _CODE_IDENTIFIER_RE.findall(claim)
    return all(identifier in evidence for identifier in identifiers)


def _evidence_spans(text: str) -> list[str]:
    return [sentence for line in text.splitlines() if line.strip()
            for sentence in split_sentences(line)]


def split_sentences(text: str) -> list[str]:
    """Cümleye ayırır; sınır işaretleri cümlelerde kalır."""

    return [piece for piece in _SENTENCE_SPLIT_RE.split(text.strip()) if piece.strip()]


def neutralize_attributions(
    answer: str, evidence_text: str, *, min_support_tokens: int = ATTRIBUTION_SUPPORT_MIN_TOKENS
) -> tuple[str, int]:
    """Makale kanıtıyla desteklenmeyen atıflı cümleleri cevaptan çıkarır.

    Desteklenen atıflar aynen kalır; atıf kalıbı taşıyıp kanıt metninde en
    az ``min_support_tokens`` anlamlı terimi bulunamayan cümle tümüyle
    çıkarılır (katlanmış metin üzerinde cerrahi düzenleme Türkçe karakter
    bozulması doğurabileceğinden). Dönüş: (denetlenmiş metin, çıkarılan
    cümle adedi).
    """

    markers = [fold_text(marker) for marker in _ATTRIBUTION_MARKERS]
    evidence_spans = _evidence_spans(evidence_text)
    removed = 0
    rebuilt: list[str] = []
    for sentence in split_sentences(answer):
        folded = fold_text(sentence)
        marker = next((m for m in markers if m in folded), None)
        if marker is None or any(_consistent_claim(sentence, span, min_tokens=min_support_tokens)
                                 for span in evidence_spans):
            rebuilt.append(sentence)
            continue
        removed += 1
    return " ".join(rebuilt), removed


def ground_answer(
    answer: str, retrieved: list[IndexedChunk], *, min_overlap: int,
) -> tuple[str, list[IndexedChunk], int]:
    """Filter each factual segment and bind citations to its supporting record.

    Unsupported claims are omitted even without an attribution phrase. Code
    fences are retained only when their body occurs in a retrieved chunk. This
    check may abstain on valid paraphrases; it does not certify arbitrary model
    statements as true. Callers must not stream the unvalidated draft.
    """
    spans = [(record, _evidence_spans(record.chunk.content)) for record in retrieved]
    kept: list[str] = []
    cited: list[IndexedChunk] = []
    removed = 0

    def cite(record: IndexedChunk) -> None:
        if record not in cited:
            cited.append(record)

    # re.split includes captured delimiter groups; finditer instead preserves
    # only complete code blocks and the prose between them.
    cursor = 0
    segments: list[tuple[str, bool]] = []
    for match in _FENCE_RE.finditer(answer):
        segments.append((answer[cursor:match.start()], False))
        segments.append((match.group(0), True))
        cursor = match.end()
    segments.append((answer[cursor:], False))
    for segment, is_code in segments:
        if is_code:
            body = "\n".join(segment.splitlines()[1:-1]).strip()
            supported = next((record for record in retrieved if body and body in record.chunk.content), None)
            if supported is None:
                removed += 1
            else:
                kept.append(segment)
                cite(supported)
            continue
        for line in segment.splitlines():
            if not line.strip():
                continue
            for sentence in split_sentences(line):
                supported = next((record for record, candidates in spans
                                  if any(_consistent_claim(sentence, span, min_tokens=min_overlap)
                                         for span in candidates)), None)
                if supported is None:
                    removed += 1
                else:
                    kept.append(sentence)
                    cite(supported)
    return ("\n\n".join(kept).strip() if cited else ""), cited, removed


def select_citations(
    answer: str, retrieved: list[IndexedChunk], *, min_overlap: int
) -> list[IndexedChunk]:
    """Cevapla en az ``min_overlap`` anlamlı terimi paylaşan getirilen bölümler.

    Sıra arama sırasını izler; getirilmemiş kayıt asla dönmez.
    """

    cited: list[IndexedChunk] = []
    for record in retrieved:
        if any(_consistent_claim(sentence, span, min_tokens=min_overlap)
               for sentence in split_sentences(answer)
               for span in _evidence_spans(record.chunk.content)):
            cited.append(record)
    return cited


def build_citations(cited: list[IndexedChunk]) -> list[SourceReference]:
    """Bölüm kayıtlarını ``SourceReference`` sözleşmesine çevirir (A0 §7.3)."""

    return [
        SourceReference(
            kind="article",
            article_id=record.article_id,
            article_revision=record.article_revision,
            chunk_index=record.chunk_index,
        )
        for record in cited
    ]


def build_section_refs(cited: list[IndexedChunk]) -> list[QaSectionRef]:
    """Atıf yapılan bölümlerin kullanıcıya gösterilecek referansları."""

    return [
        QaSectionRef(
            chunk_index=record.chunk_index,
            source_id=f"article:{record.article_id}:{record.article_revision}:{record.chunk_index}",
            heading_path=list(record.heading_path),
            anchor=record.anchor,
            url=record.canonical_url,
        )
        for record in cited
    ]


def append_source_block(answer: str, sections: list[QaSectionRef]) -> str:
    """Cevabın sonuna doğrulanmış bölüm bağlantıları bloğunu ekler."""

    if not sections:
        return answer
    lines = ["", "", "Kaynak bölümü:"]
    for section in sections:
        label = (
            " > ".join(section.heading_path)
            if section.heading_path
            else f"bölüm {section.chunk_index}"
        )
        if section.url:
            lines.append(f"- [{label}]({section.url})")
        else:
            lines.append(f"- {label} ({section.source_id})")
    return answer + "\n".join(lines)
