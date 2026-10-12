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


def split_sentences(text: str) -> list[str]:
    """Cümleye ayırır; sınır işaretleri cümlelerde kalır."""

    return [piece for piece in _SENTENCE_SPLIT_RE.split(text.strip()) if piece.strip()]


def _sentence_supported(sentence: str, evidence_tokens: set[str], *, min_tokens: int) -> bool:
    sentence_tokens = set(salient_tokens(sentence, min_length=4))
    support = sum(1 for token in sentence_tokens if token in evidence_tokens)
    return support >= min_tokens


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
    evidence_tokens = set(salient_tokens(evidence_text, min_length=4))
    removed = 0
    rebuilt: list[str] = []
    for sentence in split_sentences(answer):
        folded = fold_text(sentence)
        marker = next((m for m in markers if m in folded), None)
        if marker is None or _sentence_supported(
            sentence, evidence_tokens, min_tokens=min_support_tokens
        ):
            rebuilt.append(sentence)
            continue
        removed += 1
    return " ".join(rebuilt), removed


def select_citations(
    answer: str, retrieved: list[IndexedChunk], *, min_overlap: int
) -> list[IndexedChunk]:
    """Cevapla en az ``min_overlap`` anlamlı terimi paylaşan getirilen bölümler.

    Sıra arama sırasını izler; getirilmemiş kayıt asla dönmez.
    """

    answer_tokens = set(salient_tokens(answer, min_length=4))
    cited: list[IndexedChunk] = []
    for record in retrieved:
        chunk_tokens = set(salient_tokens(record.chunk.content, min_length=4))
        overlap = sum(1 for token in answer_tokens if token in chunk_tokens)
        if overlap >= min_overlap:
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
