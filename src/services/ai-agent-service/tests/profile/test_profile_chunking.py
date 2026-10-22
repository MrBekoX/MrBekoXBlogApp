"""Profil bölümleme testleri: deterministik, kesintisiz dilim, bütçe, FAQ, Türkçe."""

from __future__ import annotations

import hashlib

from profile_helpers import canonical_document, copy_profile, rewrite_profile, section_by_id

from agent_core.budget.guard import estimate_tokens
from agent_core.models import profile_about_url, profile_source_id
from agent_core.profile import (
    CHUNKER_VERSION,
    DEFAULT_MAX_CHUNK_TOKENS,
    chunk_document,
    load_profile_source,
)


def test_chunking_is_deterministic_and_versioned() -> None:
    document = canonical_document()
    first = chunk_document(document)
    second = chunk_document(document)

    assert first == second
    assert CHUNKER_VERSION == "profile-chunker/1"
    assert DEFAULT_MAX_CHUNK_TOKENS == 220


def test_chunks_are_contiguous_body_slices_with_stable_ids() -> None:
    document = canonical_document()
    chunks = chunk_document(document)
    per_section: dict[str, list[int]] = {}

    for chunk in chunks:
        section = document.section(chunk.section_id)
        assert section is not None
        assert chunk.text in section.body  # metin değiştirilmez (alıntı doğrulaması buna dayanır)
        assert chunk.source_id == profile_source_id(document.snapshot, chunk.section_id, chunk.chunk_index)
        assert len(chunk.source_id) <= 512
        assert chunk.url == profile_about_url(chunk.section_id) == f"/about#{chunk.section_id}"
        assert chunk.content_hash == hashlib.sha256(chunk.text.encode("utf-8")).hexdigest()
        assert estimate_tokens(chunk.text) <= DEFAULT_MAX_CHUNK_TOKENS
        per_section.setdefault(chunk.section_id, []).append(chunk.chunk_index)

    for indexes in per_section.values():
        assert indexes == list(range(len(indexes)))
    assert set(per_section) == {section.section_id for section in document.retrievable_sections()}


def test_faq_is_split_per_question_answer() -> None:
    document = canonical_document()
    faq_chunks = [chunk for chunk in chunk_document(document) if chunk.section_id == "faq"]

    assert len(faq_chunks) == 10
    assert all(chunk.text.startswith("**") and "?**" in chunk.text for chunk in faq_chunks)


def test_turkish_characters_and_notes_are_preserved() -> None:
    chunks = {chunk.section_id: chunk for chunk in chunk_document(canonical_document())}

    assert "Malatya Turgut Özal Üniversitesi" in chunks["education"].text
    agent = chunks["ai-blog-agent"]
    assert agent.notes and "ChromaDB bağlı değildir" in agent.evidence_text  # A35 notu kanıtla birlikte
    assert agent.as_of == "2026-10-21"


def test_long_paragraph_is_split_on_sentence_boundaries(tmp_path) -> None:
    target = copy_profile(tmp_path)
    sentence = "Berkay bu cümlede uzun bir test paragrafı yazıyor ve sınırı zorluyor. "
    long_body = (sentence * 40).strip()

    def lengthen(content: dict) -> None:
        section_by_id(content, "working-style")["body"] = long_body

    rewrite_profile(target, lengthen)
    document = load_profile_source(target)
    chunks = [chunk for chunk in chunk_document(document) if chunk.section_id == "working-style"]

    assert len(chunks) > 1
    assert all(estimate_tokens(chunk.text) <= DEFAULT_MAX_CHUNK_TOKENS for chunk in chunks)
    assert all(chunk.text.endswith(".") for chunk in chunks)  # cümle sınırı
    rebuilt = " ".join(chunk.text for chunk in chunks)
    assert " ".join(rebuilt.split()) == " ".join(long_body.split())


def test_non_retrievable_section_is_not_chunked(tmp_path) -> None:
    target = copy_profile(tmp_path)

    def hide(content: dict) -> None:
        section_by_id(content, "interests")["retrievable"] = False

    rewrite_profile(target, hide)
    chunks = chunk_document(load_profile_source(target))

    assert all(chunk.section_id != "interests" for chunk in chunks)
