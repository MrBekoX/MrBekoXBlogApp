"""Değerlendirme kümesinin yapı denetimleri (A10 kabul ölçütü: >=40 örnek,
kapsam listesi, bağımsız etiketleme ilkesi, geliştirme fixture'larından ayrım).
"""

from __future__ import annotations

import evals_bootstrap  # noqa: F401 - sys.path kurulumu

from agent_core.models import compute_content_hash

from evals import articles as fx
from evals import dataset as dataset_module
from evals.dataset import AREAS, CASES, EvalCase, SUITE_NAMES


def _dataset_source() -> str:
    from pathlib import Path

    return Path(dataset_module.__file__).read_text(encoding="utf-8")


def test_dataset_has_at_least_40_cases():
    assert len(CASES) >= 40


def test_dataset_covers_all_plan_areas():
    counts = {area: 0 for area in AREAS}
    for case in CASES:
        for area in case.areas:
            assert area in counts, f"bilinmeyen kapsam etiketi: {area} ({case.case_id})"
            counts[area] += 1
    empty = [area for area, count in counts.items() if count == 0]
    assert not empty, f"kapsamsız alanlar: {empty}"


def test_every_case_carries_independent_rationale():
    for case in CASES:
        assert isinstance(case, EvalCase)
        assert len(case.rationale) >= 40, f"{case.case_id} gerekçesi yok denecek kadar kısa"
        # Etiket alanı dolu ya da senaryo türü beklentiyi senaryoda taşıyor olmalı.
        has_label = any(
            value is not None
            for value in case.expected.model_dump().values()
            if not isinstance(value, list)
        ) or bool(case.expected.status_in)
        assert has_label or case.kind in ("cache", "resume"), (
            f"{case.case_id} ne etiket ne senaryo taşıyor"
        )


def test_dataset_does_not_derive_labels_from_router_rules():
    source = _dataset_source()
    # Doküman metni kural adlarını anabilir; IMPORT/ÇAĞRI olmamalıdır.
    assert "from agent_core.routing" not in source, "küme, router kural modülünü import etmemeli"
    assert "import agent_core.routing" not in source
    assert "decide_mode(" not in source, "etiket kural fonksiyonu çağrılmamalı"
    assert "classify_guidance_intent(" not in source
    assert "is_freshness_question(" not in source


def test_suites_partition_the_dataset():
    seen: set[str] = set()
    for suite in SUITE_NAMES:
        for case in cases_of(suite):
            assert case.case_id not in seen, f"{case.case_id} iki suitte"
            seen.add(case.case_id)
    assert seen == {case.case_id for case in CASES}


def cases_of(suite: str):
    return [case for case in CASES if case.suite == suite]


def test_eval_articles_are_realistic_and_separate_from_dev_fixtures():
    assert set(fx.EVAL_ARTICLES) == {
        fx.ASYNCIO_ARTICLE_ID,
        fx.PG_ARTICLE_ID,
        fx.EVENTS_ARTICLE_ID,
    }
    for snapshot in fx.EVAL_ARTICLES.values():
        # Gerçek makale yoğunluğu: çok bölüm + yüzlerce satır/kelime.
        assert snapshot.content.count("\n## ") >= 4, f"{snapshot.article_id} bölüm sayısı az"
        assert len(snapshot.content) >= 1500, f"{snapshot.article_id} makale çok kısa"
        # Hash sözleşmesi: snapshot kendi içeriğinin SHA-256 özetini taşır.
        assert snapshot.content_hash == compute_content_hash(snapshot.content)
        assert snapshot.language in ("tr", "en")
    # Geliştirme fixture'larından ayrım: küçük 'Merhaba Dünya' makalesi burada yok.
    for snapshot in fx.EVAL_ARTICLES.values():
        assert "Merhaba Dünya" not in snapshot.content


def test_web_pages_and_guidance_records_are_wired():
    assert set(fx.LOCAL_PAGES) == {fx.QUEUE_GUIDE_PATH, fx.BACKPRESSURE_PATH, fx.OUTBOX_GUIDE_PATH}
    assert fx.PROFILE_SUMMARY["name"]
    assert len(fx.PROJECT_RECORDS) >= 2
    assert len(fx.ARTICLE_CATALOG) == len(fx.EVAL_ARTICLES)
    for entry in fx.ARTICLE_CATALOG:
        assert entry["url"].startswith("https://mrbekox.dev/blog/")
