"""A6 ``assess_source`` testleri: tür sınıflaması, öncelik, kopya ayrıştırma, bağımsızlık."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

import pytest

from agent_core.web import (
    ExtractionStatus,
    SourceAssessor,
    WebSourceRecord,
)

NOW = datetime(2026, 10, 12, 9, 0, 0, tzinfo=timezone.utc)


def record(
    url: str,
    text: str = "örnek metin",
    *,
    title: str = "Sayfa",
    full_page_read: bool = True,
    published_at: datetime | None = None,
) -> WebSourceRecord:
    return WebSourceRecord(
        url=url,
        final_url=url,
        title=title,
        published_at=published_at,
        accessed_at=NOW,
        content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        extraction_status=ExtractionStatus.OK if text else ExtractionStatus.EMPTY,
        text=text,
        full_page_read=full_page_read,
    )


ASSESSOR = SourceAssessor()


# --- Tür sınıflaması ve öncelik -----------------------------------------------------


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://docs.python.org/3.13/library/asyncio-task.html", "official_docs"),
        ("https://www.rabbitmq.com/docs/confirms", "official_docs"),
        ("https://developer.mozilla.org/en-US/docs/Web/HTTP", "official_docs"),
        ("https://arxiv.org/abs/2401.00001", "original_research"),
        ("https://github.com/rabbitmq/rabbitmq-server", "project_source"),
        ("https://stackoverflow.com/questions/123/why", "forum"),
        ("https://example.com/blog/my-post", "blog"),
        ("https://blog.example.com/post", "blog"),
        ("https://example.com/news/release", "news"),
        ("https://example.com/random-page", "unknown"),
    ],
)
def test_classify_source_type(url: str, expected: str) -> None:
    assert ASSESSOR.classify_source_type(record(url)).value == expected


def test_priority_rank_and_preferred() -> None:
    docs = ASSESSOR.assess(record("https://docs.python.org/3/library/asyncio-task.html"))
    research = ASSESSOR.assess(record("https://arxiv.org/abs/2401.00001"))
    project = ASSESSOR.assess(record("https://github.com/rabbitmq/rabbitmq-server"))
    forum = ASSESSOR.assess(record("https://stackoverflow.com/q/1"))
    unknown = ASSESSOR.assess(record("https://example.com/x"))

    assert docs.priority_rank == 0 and docs.preferred
    assert research.priority_rank == 0 and research.preferred
    assert project.priority_rank == 1 and project.preferred
    assert forum.priority_rank > project.priority_rank and not forum.preferred
    assert unknown.priority_rank == 2


# --- Kopya ayrıştırma ----------------------------------------------------------------


def test_exact_duplicate_detected_by_content_hash() -> None:
    a = record("https://alpha.example/guide", "Aynı içerik metni burada.")
    b = record("https://beta.example/guide", "Aynı içerik metni burada.")
    assessment = ASSESSOR.assess(b, others=[a])
    assert assessment.duplicate_kind.value == "exact"
    assert assessment.duplicate_similarity == 1.0
    assert assessment.duplicate_of == a.to_source_reference().source_id  # DONMUŞ web kimliği
    assert any("kopya" in note for note in assessment.notes)


def test_near_duplicate_detected_by_similarity() -> None:
    base = " ".join(f"kelime{i} asyncio görev iptal davranışı belgelendi" for i in range(20))
    near = base.replace("kelime3", "kelime3x").replace("kelime9", "kelime9y")
    a = record("https://site1.example/a", base)
    b = record("https://site2.example/b", near)
    assessment = ASSESSOR.assess(b, others=[a])
    assert assessment.duplicate_kind.value == "near"
    assert assessment.duplicate_similarity is not None and assessment.duplicate_similarity >= 0.8


def test_distinct_sources_are_not_duplicates() -> None:
    a = record("https://one.example/a", "Python asyncio görevleri hakkında tamamen farklı bir metin.")
    b = record("https://two.example/b", "RabbitMQ publisher confirm protokolü ayrı bir konudur.")
    assessment = ASSESSOR.assess(b, others=[a])
    assert assessment.duplicate_kind.value == "none"
    assert assessment.duplicate_of is None


# --- Yayıncı grubu ve bağımsızlık ------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "group"),
    [
        ("https://docs.python.org/3/library/", "python.org"),
        ("https://www.python.org/psf/", "python.org"),
        ("https://blog.example.co.uk/post", "example.co.uk"),
        ("https://example.com/", "example.com"),
    ],
)
def test_publisher_group(url: str, group: str) -> None:
    from agent_core.web import publisher_group_of

    assert publisher_group_of(url) == group


def test_distinct_publisher_groups_counted() -> None:
    records = [
        record("https://docs.python.org/a"),
        record("https://www.rabbitmq.com/b"),
        record("https://mirror.python.org/c"),  # aynı python.org grubu
    ]
    assessments = [ASSESSOR.assess(r, others=records) for r in records]
    assert all(a.distinct_publisher_groups == 2 for a in assessments)  # python.org + rabbitmq.com


# --- Snippet ve tarih notları -----------------------------------------------------------


def test_snippet_only_source_is_flagged_not_preferred() -> None:
    """Snippet tam sayfa sayılmaz (plan A6)."""
    snippet_record = record("https://docs.example/reference", full_page_read=False)
    assessment = ASSESSOR.assess(snippet_record)
    assert assessment.full_page_read is False
    assert assessment.preferred is False
    assert any("snippet" in note for note in assessment.notes)


def test_missing_publication_date_note() -> None:
    assessment = ASSESSOR.assess(record("https://example.com/x", published_at=None))
    assert any("uydurulmadı" in note for note in assessment.notes)


def test_empty_extraction_flagged_unusable() -> None:
    empty = record("https://example.com/empty", text="")
    assessment = ASSESSOR.assess(empty)
    assert any("çıkarılamadı" in note and "kullanılmamalı" in note for note in assessment.notes)


def test_source_id_matches_frozen_contract_shape() -> None:
    """source_id DONMUŞ A1 web kimliği biçiminde türetilir (web:<hash>:<damga>)."""
    assessment = ASSESSOR.assess(record("https://example.com/x"))
    assert assessment.source_id.startswith("web:")
