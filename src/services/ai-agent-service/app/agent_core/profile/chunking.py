"""Profil bölümleri için deterministik parçalama (Who am I RAG).

Davranış sözleşmesi:

- Parça sınırları anlam sınırlarıdır: paragraf (boş satır), madde imi
  (``-``/``*``) ve FAQ'ta her soru/cevap paragrafı. Bir bölüm başlığı (section)
  hiçbir zaman başka bölümle aynı parçada birleşmez.
- Parçalar bölüm gövdesinin KESİNTİSİZ dilimidir (``body[start:end]``); metin
  değiştirilmez, böylece alıntı doğrulaması kaynak metne karşı yapılır.
- Bütçe: parça başına ~``DEFAULT_MAX_CHUNK_TOKENS`` (``budget.guard.
  estimate_tokens``). Bitişik birimler bütçe içinde birleştirilir; tek başına
  bütçeyi aşan birim cümle, gerekirse kelime sınırından bölünür.
- FAQ bölümünde her soru/cevap ayrı parçadır (soru odaklı retrieval).
- UTF-8/Türkçe güvenlidir: karakter düzeyinde dilimleme yapılır, bayt değil.
- ``CHUNKER_VERSION`` parça kimliklerinin/indeksin önbellek anahtarına girer;
  bölümleme kuralı değişirse sürüm artırılır.
"""

from __future__ import annotations

import hashlib
import re

from pydantic import NonNegativeInt, PositiveInt

from ..budget.guard import estimate_tokens
from ..models import BusinessModel, HashHex, profile_about_url, profile_source_id
from .source import ProfileDocument, ProfileSection

__all__ = ["CHUNKER_VERSION", "DEFAULT_MAX_CHUNK_TOKENS", "ProfileChunk", "chunk_document", "chunk_section"]

CHUNKER_VERSION = "profile-chunker/1"
DEFAULT_MAX_CHUNK_TOKENS = 220

_BULLET_RE = re.compile(r"^\s{0,3}[-*]\s+")
_SENTENCE_END_RE = re.compile(r"[.!?…]+[\"')\]]*(?:\s+|$)")
_WORD_RE = re.compile(r"\S+")


class ProfileChunk(BusinessModel):
    """Profil retrieval birimi; kimliği pinlenmiş profil sürümüne bağlıdır."""

    source_id: str
    section_id: str
    chunk_index: NonNegativeInt
    text: str
    content_hash: HashHex
    heading_path: list[str]
    title: str
    title_en: str | None = None
    anchor: str
    kind: str
    #: Bölümün editör notları (ör. beyan ile depo mimarisi farkı); kanıtla birlikte gösterilir.
    notes: list[str] = []
    #: Beyan tarihi / durum (``claim``): modele tarihli beyan bağlamı olarak verilir.
    as_of: str | None = None
    status: str | None = None
    token_count: PositiveInt

    @property
    def url(self) -> str:
        return profile_about_url(self.section_id)

    @property
    def evidence_text(self) -> str:
        """Modele gösterilen ve alıntıların doğrulandığı metin: gövde dilimi + notlar."""

        if not self.notes:
            return self.text
        return "\n".join([self.text, *(f"Editör notu: {note}" for note in self.notes)])


def _trimmed(body: str, start: int, end: int) -> tuple[int, int]:
    while start < end and body[start].isspace():
        start += 1
    while end > start and body[end - 1].isspace():
        end -= 1
    return start, end


def _unit_spans(body: str) -> list[tuple[int, int]]:
    """Paragraf ve madde imi birimlerinin (start, end) dilimleri; belge sırasıyla."""

    spans: list[tuple[int, int]] = []
    current_start: int | None = None
    current_end = 0
    offset = 0
    for line in body.splitlines(keepends=True):
        line_start = offset
        line_end = offset + len(line)
        offset = line_end
        if not line.strip():
            if current_start is not None:
                spans.append(_trimmed(body, current_start, current_end))
                current_start = None
            continue
        if _BULLET_RE.match(line) and current_start is not None:
            spans.append(_trimmed(body, current_start, current_end))
            current_start = None
        if current_start is None:
            current_start = line_start
        current_end = line_end
    if current_start is not None:
        spans.append(_trimmed(body, current_start, current_end))
    return [(start, end) for start, end in spans if end > start]


def _tokens(body: str, start: int, end: int) -> int:
    return estimate_tokens(body[start:end])


def _split_by(body: str, start: int, end: int, pattern: re.Pattern[str], *, sentence: bool) -> list[tuple[int, int]]:
    pieces: list[tuple[int, int]] = []
    segment = body[start:end]
    if sentence:
        cursor = 0
        for match in pattern.finditer(segment):
            pieces.append((start + cursor, start + match.end()))
            cursor = match.end()
        if cursor < len(segment):
            pieces.append((start + cursor, end))
    else:
        pieces = [(start + m.start(), start + m.end()) for m in pattern.finditer(segment)]
    trimmed: list[tuple[int, int]] = []
    for piece_start, piece_end in pieces:
        piece_start, piece_end = _trimmed(body, piece_start, piece_end)
        if piece_end > piece_start:
            trimmed.append((piece_start, piece_end))
    return trimmed


def _pack(body: str, spans: list[tuple[int, int]], max_tokens: int) -> list[tuple[int, int]]:
    """Bitişik dilimleri bütçe içinde birleştirir (dilimler belge sırasındadır)."""

    packed: list[tuple[int, int]] = []
    current: tuple[int, int] | None = None
    for span in spans:
        if current is None:
            current = span
            continue
        if _tokens(body, current[0], span[1]) <= max_tokens:
            current = (current[0], span[1])
        else:
            packed.append(current)
            current = span
    if current is not None:
        packed.append(current)
    return packed


def _fit(body: str, span: tuple[int, int], max_tokens: int) -> list[tuple[int, int]]:
    """Bütçeyi aşan tek birimi cümle → kelime sınırından böler."""

    start, end = span
    if _tokens(body, start, end) <= max_tokens:
        return [span]
    sentences = _split_by(body, start, end, _SENTENCE_END_RE, sentence=True)
    result: list[tuple[int, int]] = []
    for sentence in _pack(body, sentences, max_tokens):
        if _tokens(body, *sentence) <= max_tokens:
            result.append(sentence)
            continue
        words = _split_by(body, sentence[0], sentence[1], _WORD_RE, sentence=False)
        result.extend(_pack(body, words, max_tokens))
    return result


def _section_spans(section: ProfileSection, max_tokens: int) -> list[tuple[int, int]]:
    body = section.body
    units: list[tuple[int, int]] = []
    for span in _unit_spans(body):
        units.extend(_fit(body, span, max_tokens))
    if section.kind == "faq":
        # FAQ: her soru/cevap paragrafı kendi parçasıdır (birleştirme yok).
        return units
    return _pack(body, units, max_tokens)


def chunk_section(
    document: ProfileDocument, section: ProfileSection, *, max_tokens: int = DEFAULT_MAX_CHUNK_TOKENS
) -> list[ProfileChunk]:
    """Tek bölümü parçalara ayırır; ``chunk_index`` bölüm içinde 0'dan başlar."""

    chunks: list[ProfileChunk] = []
    claim = section.claim or {}
    as_of = claim.get("as_of") if isinstance(claim.get("as_of"), str) else None
    status = claim.get("status") if isinstance(claim.get("status"), str) else None
    for index, (start, end) in enumerate(_section_spans(section, max_tokens)):
        text = section.body[start:end]
        chunk = ProfileChunk(
            source_id=profile_source_id(document.snapshot, section.section_id, index),
            section_id=section.section_id,
            chunk_index=index,
            text=text,
            content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            heading_path=list(section.heading_path),
            title=section.title_for("tr"),
            title_en=section.title.get("en"),
            anchor=section.anchor,
            kind=section.kind,
            notes=list(section.notes),
            as_of=as_of,
            status=status,
            token_count=1,
        )
        chunks.append(chunk.model_copy(update={"token_count": estimate_tokens(chunk.evidence_text)}))
    return chunks


def chunk_document(document: ProfileDocument, *, max_tokens: int = DEFAULT_MAX_CHUNK_TOKENS) -> list[ProfileChunk]:
    """Yalnız ``retrievable`` bölümleri belge sırasıyla parçalar."""

    chunks: list[ProfileChunk] = []
    for section in document.retrievable_sections():
        chunks.extend(chunk_section(document, section, max_tokens=max_tokens))
    return chunks
