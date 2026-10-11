"""Ortak anchor sözleşmesi testleri.

Kabul ölçütü: "Başlık anchor'ları ortak fixture'larla doğrulanıyor."
Tabloların asıl kaynağı ``fixtures.py``'dir; chunker testleri de aynı
örnek metnin anchor'larını buradaki kurallarla karşılaştırır.
"""

from __future__ import annotations

import pytest

import fixtures
from agent_core.content import fold_text, heading_anchor, slugify_heading


@pytest.mark.parametrize(["heading", "expected"], fixtures.ANCHOR_FIXTURES)
def test_slugify_contract(heading: str, expected: str) -> None:
    assert slugify_heading(heading) == expected


@pytest.mark.parametrize(["headings", "expected"], fixtures.DUPLICATE_ANCHOR_CASES)
def test_duplicate_headings_get_ordinal_suffixes(
    headings: list[str], expected: list[str]
) -> None:
    seen: dict[str, int] = {}
    produced = [heading_anchor(heading, seen) for heading in headings]
    assert produced == expected


def test_anchor_production_is_deterministic() -> None:
    seen_first: dict[str, int] = {}
    first_run = [heading_anchor(heading, seen_first) for heading, _ in fixtures.ANCHOR_FIXTURES]
    seen_second: dict[str, int] = {}
    second_run = [heading_anchor(heading, seen_second) for heading, _ in fixtures.ANCHOR_FIXTURES]
    assert first_run == second_run


def test_fold_turkish_case_pairs() -> None:
    assert fold_text("Örnekşehir") == "orneksehir"
    assert fold_text("IRMAK") == "irmak"
    assert fold_text("IŞIK") == "isik"
    assert fold_text("BAŞLIK") == "baslik"


def test_sample_markdown_anchors_follow_document_order() -> None:
    from agent_core.content import chunk_article
    from agent_core.content.config import ChunkingConfig

    prepared = chunk_article(
        fixtures.make_sample_snapshot(), ChunkingConfig(max_chars=1024)
    )
    # Belge sırası: Giriş → Kurulum → Kullanım → Kod açıklaması → Kurulum (2.).
    # Tekrarlanan "## Kurulum" -2 son ekini alır (sözleşme m.4).
    assert [item.anchor for item in prepared] == [
        "giris",
        "kurulum",
        "kullanim",
        "kod-aciklamasi",
        "kurulum-2",
    ]
