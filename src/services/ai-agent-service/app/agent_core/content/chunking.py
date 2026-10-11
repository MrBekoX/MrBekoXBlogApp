"""Markdown korumalı bölümleme (A3).

Davranış sözleşmesi:

- ATX başlıkları (``#`` .. ``######``) bölüm açar; başlık yolu makale
  başlığını kök alarak tutulur; ``anchors.heading_anchor`` ile bölüm anchor'ı
  üretilir (tek makalelik geçişte tekrarlanan başlıklar ``-2``, ``-3`` alır).
- Fenced kod blokları (`` ``` `` veya ``~~~``) tek parça korunur; fence
  içindeki ``#`` satırları başlık sayılmaz ve hiçbir parça fence içinden
  bölünmez. Kapatılmamış fence belge sonuna kadar fence sayılır. Girintiyle
  kod blokları kapsam dışıdır.
- Parçalar kaynağın kesintisiz dilimidir: ``chunk.content ==
  content[char_start:char_end]`` (citation offset sözleşmesi, A0 §4).
- Uzun bölümler paragraf → cümle → kelime sınırı sırasıyla bölünür; üst
  sınır ``ChunkingConfig`` ile embedding modelinden türetilir. Tek başına
  sınırı aşan fenced blok bölünmeden kendi parçasında taşınır (belgeli
  istisna).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..errors import AgentErrorCode, PortError
from ..models import ArticleChunk, ArticleSnapshot
from .anchors import heading_anchor
from .config import ChunkingConfig

__all__ = ["PreparedChunk", "chunk_article", "embedded_text"]

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_FENCE_RE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
_SENTENCE_END_RE = re.compile(r"[.!?…]+[\"')\]]*(?:\s+|$)")


@dataclass(frozen=True)
class PreparedChunk:
    """Bölümleyici çıktısı: parça + bölüm bağlamı (başlık yolu ve anchor)."""

    chunk: ArticleChunk
    heading_path: tuple[str, ...]
    anchor: str


@dataclass(frozen=True)
class _Block:
    """Kaynağın bir dilimi: başlık, paragraf veya fenced kod bloğu."""

    kind: str  # "heading" | "para" | "fence"
    start: int
    end: int
    level: int = 0
    text: str = ""


@dataclass(frozen=True)
class _Section:
    """Bir başlığın (veya ilk başlıktan önceki girişin) altındaki blok kümesi."""

    heading: str | None
    heading_path: tuple[str, ...]
    anchor: str
    blocks: tuple[_Block, ...]


def _scan_blocks(content: str) -> list[_Block]:
    """Satır satır tarar; fence durumu başlık algılamasını bastırır."""

    blocks: list[_Block] = []
    para_start: int | None = None
    fence: tuple[str, int, int] | None = None  # (fence karakteri, uzunluk, başlangıç)
    offset = 0
    for raw_line in content.splitlines(keepends=True):
        line_end = offset + len(raw_line)
        stripped = raw_line.strip()
        if fence is not None:
            fence_char, fence_len, fence_start = fence
            if len(stripped) >= fence_len and set(stripped) == {fence_char}:
                blocks.append(_Block("fence", fence_start, line_end))
                fence = None
            offset = line_end
            continue
        fence_match = _FENCE_RE.match(raw_line)
        if fence_match is not None:
            if para_start is not None:
                blocks.append(_Block("para", para_start, offset))
                para_start = None
            marker = fence_match.group(1)
            fence = (marker[0], len(marker), offset)
            offset = line_end
            continue
        heading_match = _HEADING_RE.match(raw_line)
        if heading_match is not None:
            if para_start is not None:
                blocks.append(_Block("para", para_start, offset))
                para_start = None
            blocks.append(
                _Block(
                    "heading",
                    offset,
                    line_end,
                    level=len(heading_match.group(1)),
                    text=heading_match.group(2),
                )
            )
            offset = line_end
            continue
        if stripped:
            if para_start is None:
                para_start = offset
        elif para_start is not None:
            blocks.append(_Block("para", para_start, offset))
            para_start = None
        offset = line_end
    if fence is not None:
        fence_start = fence[2]
        blocks.append(_Block("fence", fence_start, len(content)))
    elif para_start is not None:
        blocks.append(_Block("para", para_start, len(content)))
    return blocks


def _build_sections(content: str, title: str) -> list[_Section]:
    """Blokları bölümlere toplar; başlık yollarını ve anchor'ları üretir."""

    sections: list[_Section] = []
    open_headings: dict[int, str] = {}
    seen: dict[str, int] = {}
    current: list[_Block] = []
    current_heading: str | None = None
    current_path: tuple[str, ...] = (title,)
    current_anchor: str = heading_anchor(title, seen)

    def flush() -> None:
        if current:
            sections.append(
                _Section(current_heading, current_path, current_anchor, tuple(current))
            )
            current.clear()

    for block in _scan_blocks(content):
        if block.kind == "heading":
            flush()
            for level in [lv for lv in open_headings if lv >= block.level]:
                del open_headings[level]
            open_headings[block.level] = block.text
            current_heading = block.text
            current_path = (title, *(open_headings[lv] for lv in sorted(open_headings)))
            current_anchor = heading_anchor(block.text, seen)
        current.append(block)
    flush()
    return sections


def _trimmed_span(content: str, start: int, end: int) -> tuple[int, int]:
    """Boşluk kırpılmış dilim sınırları; ofset bütünlüğü burada korunur."""

    while start < end and content[start].isspace():
        start += 1
    while end > start and content[end - 1].isspace():
        end -= 1
    return start, end


def _sentence_offsets(content: str, start: int, end: int) -> list[tuple[int, int]]:
    """Cümle sınırlarını mutlak ofsetlere çevirir; sınır yoksa tek cümle."""

    offsets: list[tuple[int, int]] = []
    piece_start = start
    for match in _SENTENCE_END_RE.finditer(content, start, end):
        offsets.append((piece_start, match.end()))
        piece_start = match.end()
    if piece_start < end:
        offsets.append((piece_start, end))
    elif offsets:
        prev_start = offsets[-1][0]
        offsets[-1] = (prev_start, end)
    return offsets or [(start, end)]


def _hard_word_splits(content: str, start: int, end: int, max_chars: int) -> list[tuple[int, int]]:
    """Cümleden uzun parçayı kelime sınırından keser; kelimesizse sert keser."""

    offsets: list[tuple[int, int]] = []
    cursor = start
    while end - cursor > max_chars:
        cut = cursor + max_chars
        space_at = content.rfind(" ", cursor, cut)
        if space_at > cursor:
            cut = space_at
        offsets.append((cursor, cut))
        cursor = cut
        while cursor < end and content[cursor].isspace():
            cursor += 1
    if cursor < end:
        offsets.append((cursor, end))
    return offsets


def _pack(
    units: list[tuple[str, int, int]], content: str, max_chars: int
) -> list[tuple[list[str], int, int]]:
    """Birimleri sınırı aşmayacak biçimde ardışık paketler; dilimler bitişik kalır."""

    pieces: list[tuple[list[str], int, int]] = []
    piece_start: int | None = None
    piece_end = 0
    piece_kinds: list[str] = []
    for kind, unit_start, unit_end in units:
        if piece_start is None:
            piece_start, piece_end, piece_kinds = unit_start, unit_end, [kind]
            continue
        span_start, span_end = _trimmed_span(content, piece_start, unit_end)
        if span_end - span_start > max_chars:
            trimmed_start, trimmed_end = _trimmed_span(content, piece_start, piece_end)
            pieces.append((piece_kinds, trimmed_start, trimmed_end))
            piece_start, piece_kinds = unit_start, [kind]
        piece_end = unit_end
    if piece_start is not None:
        trimmed_start, trimmed_end = _trimmed_span(content, piece_start, piece_end)
        pieces.append((piece_kinds, trimmed_start, trimmed_end))
    return pieces


def _split_section(content: str, section: _Section, max_chars: int) -> list[tuple[int, int]]:
    """Bölümü parça dilimlerine böler; fenced blok asla ikiye bölünmez."""

    units: list[tuple[str, int, int]] = []
    for block in section.blocks:
        start, end = _trimmed_span(content, block.start, block.end)
        if start < end:
            units.append((block.kind, start, end))
    if not units:
        return []
    result: list[tuple[int, int]] = []
    for kinds, piece_start, piece_end in _pack(units, content, max_chars):
        if piece_end - piece_start <= max_chars:
            result.append((piece_start, piece_end))
            continue
        if kinds == ["fence"]:
            # Kod bloğu bütünlüğü boyut sınırından önceliklidir (belgeli istisna).
            result.append((piece_start, piece_end))
            continue
        sentence_units: list[tuple[str, int, int]] = []
        for start, end in _sentence_offsets(content, piece_start, piece_end):
            if end - start <= max_chars:
                sentence_units.append(("para", start, end))
            else:
                sentence_units.extend(
                    ("para", s, e) for s, e in _hard_word_splits(content, start, end, max_chars)
                )
        result.extend((s, e) for _kinds, s, e in _pack(sentence_units, content, max_chars))
    return result


def chunk_article(snapshot: ArticleSnapshot, config: ChunkingConfig) -> list[PreparedChunk]:
    """Snapshot içeriğini hiyerarşi ve kod bloğu korumalı parçalara böler.

    Raises:
        PortError: ``validation_error`` — içerik boş veya yalnız boşluk.
    """

    if not snapshot.content.strip():
        raise PortError(
            AgentErrorCode.VALIDATION_ERROR,
            "bölümleme boş makale içeriğini kabul etmez",
            port="ContentChunker",
        )
    prepared: list[PreparedChunk] = []
    chunk_index = 0
    for section in _build_sections(snapshot.content, snapshot.title):
        for start, end in _split_section(snapshot.content, section, config.max_chars):
            text = snapshot.content[start:end]
            if not text:
                continue
            chunk = ArticleChunk(
                article_id=snapshot.article_id,
                article_revision=snapshot.article_revision,
                chunk_index=chunk_index,
                content=text,
                heading=section.heading,
                char_start=start,
                char_end=end,
            )
            prepared.append(PreparedChunk(chunk, section.heading_path, section.anchor))
            chunk_index += 1
    return prepared


def embedded_text(heading_path: tuple[str, ...] | list[str], content: str) -> str:
    """Gömme metni: başlık yolu öneki + parça içeriği (bağlamsal bağlam eki).

    Parça kaynak bağlamını kaybettiğinde arama ve cevap üretimi zorlaşır;
    başlık yolu öneki bu kaybı telafi eder [ENG-CONTEXTUAL#C1]
    [ENG-CONTEXTUAL#C2].
    """

    prefix = " > ".join(heading_path)
    return f"{prefix}\n\n{content}" if prefix else content
