"""Bölümleyici testleri: hiyerarşi, kod bloğu bütünlüğü, ofset bütünlüğü, boyutlandırma."""

from __future__ import annotations

import pytest

import fixtures
from agent_core.content import ChunkingConfig, EmbeddingModelConfig, chunk_article
from agent_core.errors import AgentErrorCode, PortError


def test_sample_markdown_heading_paths_and_order() -> None:
    snapshot = fixtures.make_sample_snapshot()
    prepared = chunk_article(snapshot, ChunkingConfig(max_chars=1024))
    paths = [item.heading_path for item in prepared]
    assert paths == [
        ("Python Rehberi", "Giriş"),
        ("Python Rehberi", "Giriş", "Kurulum"),
        ("Python Rehberi", "Giriş", "Kullanım"),
        ("Python Rehberi", "Giriş", "Kullanım", "Kod açıklaması"),
        ("Python Rehberi", "Giriş", "Kurulum"),
    ]
    assert [item.chunk.heading for item in prepared] == [
        "Giriş",
        "Kurulum",
        "Kullanım",
        "Kod açıklaması",
        "Kurulum",
    ]
    assert [item.chunk.chunk_index for item in prepared] == [0, 1, 2, 3, 4]


def test_offsets_slice_content_exactly() -> None:
    snapshot = fixtures.make_sample_snapshot()
    content = snapshot.content
    for item in chunk_article(snapshot, ChunkingConfig(max_chars=64)):
        chunk = item.chunk
        assert content[chunk.char_start : chunk.char_end] == chunk.content
        assert chunk.content == chunk.content.strip(" \n\t")


def test_code_fence_stays_whole() -> None:
    prepared = chunk_article(fixtures.make_sample_snapshot(), ChunkingConfig(max_chars=1024))
    fence_chunks = [item for item in prepared if "```python" in item.chunk.content]
    assert len(fence_chunks) == 1
    fence_chunk = fence_chunks[0].chunk
    assert fence_chunk.content.count("```") == 2  # açılış ve kapanış aynı parçada
    assert "return str(deger)" in fence_chunk.content


def test_heading_inside_fence_is_not_a_heading() -> None:
    prepared = chunk_article(fixtures.make_sample_snapshot(), ChunkingConfig(max_chars=1024))
    headings = [item.chunk.heading for item in prepared]
    assert "bu satır başlık DEĞİLDİR" not in headings
    fence_items = [item for item in prepared if "```python" in item.chunk.content]
    assert fence_items[0].chunk.heading == "Kullanım"


def test_long_section_splits_within_limit_and_loses_no_content() -> None:
    content = fixtures.paragraph("Bölme", 24)
    snapshot = fixtures.make_index_snapshot(content, title="Uzun Metin")
    config = ChunkingConfig(max_chars=300)
    prepared = chunk_article(snapshot, config)
    assert len(prepared) > 1
    for item in prepared:
        assert len(item.chunk.content) <= config.max_chars
        assert content[item.chunk.char_start : item.chunk.char_end] == item.chunk.content
        assert item.heading_path == ("Uzun Metin",)
    for first, second in zip(prepared, prepared[1:]):
        # Parçalar arası yalnız kırpılan boşluk kalır; içerik kaybı yoktur.
        gap = content[first.chunk.char_end : second.chunk.char_start]
        assert gap.strip() == ""
    assert content[prepared[0].chunk.char_start : prepared[-1].chunk.char_end].strip() == content


def test_single_giant_fenced_block_is_kept_whole() -> None:
    fence_body = "\n".join(f"satir_{index} = 'deger_{index}'" for index in range(12))
    content = f"```python\n{fence_body}\n```"
    snapshot = fixtures.make_index_snapshot(content, title="Kod")
    prepared = chunk_article(snapshot, ChunkingConfig(max_chars=60))
    assert len(prepared) == 1  # belgeli istisna: kod bloğu bölünmez
    assert prepared[0].chunk.content == content


def test_tilde_fence_supported() -> None:
    content = "## Deney\n\n~~~\nplain kayıt\n# bu da başlık değil\n~~~"
    snapshot = fixtures.make_index_snapshot(content, title="Deneyler")
    prepared = chunk_article(snapshot, ChunkingConfig(max_chars=1024))
    assert len(prepared) == 1
    assert "~~~" in prepared[0].chunk.content
    assert "bu da başlık değil" in prepared[0].chunk.content


def test_unclosed_fence_runs_to_end_of_document() -> None:
    content = "## Açık\n\n```python\nx = 1\ny = 2"
    snapshot = fixtures.make_index_snapshot(content, title="Açık Uçlar")
    prepared = chunk_article(snapshot, ChunkingConfig(max_chars=1024))
    assert len(prepared) == 1
    assert "y = 2" in prepared[0].chunk.content


def test_preamble_without_headings_uses_title_path() -> None:
    content = fixtures.paragraph("Giriş", 2)
    snapshot = fixtures.make_index_snapshot(content, title="Sade")
    prepared = chunk_article(snapshot, ChunkingConfig(max_chars=1024))
    assert len(prepared) == 1
    assert prepared[0].heading_path == ("Sade",)
    assert prepared[0].chunk.heading is None


def test_config_derives_max_chars_from_embedding_model() -> None:
    model = EmbeddingModelConfig(model_id="m", dimensions=768, max_chunk_tokens=512, chars_per_token=4)
    assert ChunkingConfig.for_model(model).max_chars == 2048
    small = EmbeddingModelConfig(model_id="m", dimensions=768, max_chunk_tokens=128, chars_per_token=2)
    assert ChunkingConfig.for_model(small).max_chars == 256


def test_empty_content_is_rejected() -> None:
    snapshot = fixtures.make_index_snapshot("   \n\t ", title="Boş")
    with pytest.raises(PortError) as excinfo:
        chunk_article(snapshot, ChunkingConfig(max_chars=256))
    assert excinfo.value.code is AgentErrorCode.VALIDATION_ERROR
