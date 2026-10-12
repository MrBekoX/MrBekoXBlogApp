"""A6 ``AssessSourceTool.assess_many`` testleri: öz-kopya dışlaması (F1).

A7-rapor.md F1: ``assess_many`` verilen listenin tamamını ``others`` olarak
geçtiğinde her kayıt kendi içerik hash'iyle karşılaştırılıp kendi kopyası
gibi işaretleniyordu. Düzeltilmiş sözleşme:
- hiçbir kayıt kendisiyle (aynı kaynak girdisiyle) kopya işaretlenmez;
- içerik hash'i eşit olan FARKLI kayıtlar yine de karşılıklı kopyadır.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from agent_core.web import (
    AssessSourceTool,
    ExtractionStatus,
    WebSourceRecord,
)

from .web_helpers import run

NOW = datetime(2026, 10, 12, 9, 0, 0, tzinfo=timezone.utc)

TOOL = AssessSourceTool()


def record(
    url: str,
    text: str = "örnek metin",
    *,
    accessed_at: datetime = NOW,
) -> WebSourceRecord:
    return WebSourceRecord(
        url=url,
        final_url=url,
        title="Sayfa",
        published_at=None,
        accessed_at=accessed_at,
        content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        extraction_status=ExtractionStatus.OK if text else ExtractionStatus.EMPTY,
        text=text,
        full_page_read=True,
    )


def test_assess_many_never_flags_record_as_duplicate_of_itself() -> None:
    """Hiçbir kayıt kendi kaynak kimliğiyle kopya olarak işaretlenmez (F1-a)."""
    records = [
        record("https://docs.python.org/a", "Python asyncio görevleri hakkında bir metin."),
        record("https://www.rabbitmq.com/b", "RabbitMQ publisher confirm protokolü ayrı bir konudur."),
        record("https://example.com/c", "Üçüncü ve tıpkıbaşka bir kaynak içeriği."),
    ]
    assessments = run(TOOL.assess_many(records))
    assert len(assessments) == len(records)
    for record_, assessment in zip(records, assessments):
        assert assessment.duplicate_kind.value == "none", f"{record_.final_url} kendisiyle kopya"
        assert assessment.duplicate_of is None


def test_assess_many_still_flags_true_cross_duplicates() -> None:
    """İçerik hash'i eşit İKİ farklı kayıt karşılıklı tam kopya kalır (F1-b)."""
    shared = "Aynı içerikten paylaşılan tam kopya makale metni."
    a = record("https://alpha.example/guide", shared)
    b = record("https://beta.example/guide", shared)
    assessments = run(TOOL.assess_many([a, b]))
    a_id = a.to_source_reference().source_id
    b_id = b.to_source_reference().source_id
    assert assessments[0].duplicate_kind.value == "exact"
    assert assessments[0].duplicate_of == b_id
    assert assessments[0].duplicate_similarity == 1.0
    assert assessments[1].duplicate_kind.value == "exact"
    assert assessments[1].duplicate_of == a_id


def test_assess_many_excludes_same_source_entry_listed_twice() -> None:
    """Aynı kaynak girdisinin (url+erişim damgası) tekrarı kopya sayılmaz."""
    entry = record("https://example.com/dup", "Aynı girdiden iki kopya girdi.")
    assessments = run(TOOL.assess_many([entry, entry]))
    assert all(a.duplicate_kind.value == "none" and a.duplicate_of is None for a in assessments)


def test_assess_many_mixed_batch_keeps_distinct_assessment() -> None:
    """Karışık kümede yalnız gerçek kopya çifti işaretlenir; diğer kayıt temiz kalır."""
    shared = "Kopya olan ikilinin ortak sayfa içeriği burada."
    dup_a = record("https://one.example/x", shared)
    dup_b = record("https://two.example/x", shared)
    distinct = record("https://three.example/y", "Tamamen ayrı konuda tekil bir içerik.")
    assessments = run(TOOL.assess_many([dup_a, dup_b, distinct]))
    assert assessments[0].duplicate_of == dup_b.to_source_reference().source_id
    assert assessments[1].duplicate_of == dup_a.to_source_reference().source_id
    assert assessments[2].duplicate_kind.value == "none"
    assert assessments[2].duplicate_of is None
