"""Profil lexical retrieval testleri + W7 offline soru kümesi ölçümü.

Ölçüm GERÇEK canonical kaynak ve GERÇEK lexical retriever ile yapılır (test
double yok); yine de bu bir LLM kalite ölçümü DEĞİLDİR. Kümedeki sorular
retriever'la birlikte yazıldı; bağımsız (held-out) bir benchmark değildir.
"""

from __future__ import annotations

import sys
from pathlib import Path

from profile_helpers import canonical_document, copy_profile, rewrite_profile, section_by_id

from agent_core.models import AgentMode
from agent_core.profile import (
    MODE_RETRIEVAL_BUDGETS,
    ProfileRetriever,
    budget_for_mode,
    load_profile_source,
)

_SERVICE_ROOT = Path(__file__).resolve().parents[2]
if str(_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SERVICE_ROOT))

from evals.profile_retrieval import load_cases, measure  # noqa: E402


def test_eval_question_set_covers_sections_and_acceptance_ids() -> None:
    payload = load_cases()
    document = canonical_document()
    cases = payload["cases"]
    retrieval = [case for case in cases if case["kind"] == "retrieval"]
    by_section: dict[str, set[str]] = {}
    for case in retrieval:
        for section_id in case["expected_sections"]:
            by_section.setdefault(section_id, set()).add(case["language"])
            assert document.section(section_id) is not None, section_id

    important = {
        section.section_id
        for section in document.sections
        if section.kind in {"bio", "project", "ai_work", "oss", "contact"} and section.section_id != "overview"
    } | {"overview"}
    for section_id in important:
        assert by_section.get(section_id, set()) >= {"tr", "en"}, f"{section_id} için TR+EN soru eksik"

    acceptance = {aid for case in cases for aid in case.get("acceptance", [])}
    required = {f"A{n:02d}" for n in range(1, 23)} | {"A31", "A35"}
    required -= {"A20", "A21"}  # model isteği/çıktısı: runner testlerinde (test_profile_runner)
    assert required <= acceptance, sorted(required - acceptance)


def test_eval_retrieval_hit_rate_with_real_lexical_retriever() -> None:
    report = measure()
    summary = report.summary()
    print("\nprofile retrieval eval:", summary)  # pytest -s ile görünür

    assert report.retrieval_total >= 60
    assert report.hit_rate >= 0.95, report.failures()
    assert report.precision_at_1 >= 0.9
    assert report.insufficient_ok == report.insufficient_total
    assert report.policy_ok == report.policy_total, report.failures()
    assert report.routing_ok == report.routing_total, report.failures()
    assert not report.failures(), [(f.case_id, f.detail) for f in report.failures()]


def test_index_is_built_once_per_snapshot_and_queries_are_cached() -> None:
    document = canonical_document()
    retriever = ProfileRetriever()
    budget = budget_for_mode(AgentMode.FAST)

    first = retriever.retrieve(document, "Hangi üniversitede okudu?", language="tr", budget=budget)
    second = retriever.retrieve(document, "  hangi ÜNİVERSİTEDE okudu? ", language="tr", budget=budget)
    retriever.retrieve(document, "Vibeo nedir?", language="tr", budget=budget)

    assert retriever.index_builds == 1
    assert first.cached is False and second.cached is True  # normalize sorgu aynı anahtar
    assert second.section_ids == first.section_ids == ["education"]
    other_budget = retriever.retrieve(document, "Hangi üniversitede okudu?", language="tr", budget=budget_for_mode(AgentMode.DEEP_RESEARCH))
    assert other_budget.cached is False  # top-k/bütçe anahtarın parçası


def test_new_revision_gets_its_own_index_and_no_stale_results(tmp_path) -> None:
    target = copy_profile(tmp_path)
    retriever = ProfileRetriever()
    budget = budget_for_mode(AgentMode.FAST)
    old_document = load_profile_source(target)
    old = retriever.retrieve(old_document, "Hangi üniversitede okudu?", language="tr", budget=budget)

    def change(content: dict) -> None:
        section_by_id(content, "education")["body"] = "- **Eğitim:** Yeni Test Üniversitesi, Bilgisayar Mühendisliği (2000–2004)."

    rewrite_profile(target, change, revision=old_document.revision + 1)
    new_document = load_profile_source(target)
    new = retriever.retrieve(new_document, "Hangi üniversitede okudu?", language="tr", budget=budget)

    assert retriever.index_builds == 2
    assert new.cached is False
    assert "Demo" in old.chunks[0].chunk.text
    assert "Yeni Test Üniversitesi" in new.chunks[0].chunk.text
    assert new.chunks[0].chunk.source_id.startswith(f"profile:sample-author:{new_document.revision}:")


def test_mode_budgets_bound_top_k_and_context_tokens() -> None:
    document = canonical_document()
    retriever = ProfileRetriever()
    question = "Sample'ın projeleri, yapay zekâ çalışmaları, mimari yaklaşımı ve eğitmenliği nedir?"

    assert {mode: (b.top_k, b.max_context_tokens) for mode, b in MODE_RETRIEVAL_BUDGETS.items()} == {
        AgentMode.FAST: (4, 1800),
        AgentMode.ANALYSIS: (6, 2800),
        AgentMode.DEEP_RESEARCH: (8, 3800),
    }
    for mode, budget in MODE_RETRIEVAL_BUDGETS.items():
        result = retriever.retrieve(document, question, language="tr", budget=budget)
        assert len(result.chunks) <= budget.top_k
        assert result.context_tokens <= budget.max_context_tokens
    deep = retriever.retrieve(document, question, language="tr", budget=budget_for_mode(AgentMode.DEEP_RESEARCH))
    fast = retriever.retrieve(document, question, language="tr", budget=budget_for_mode(AgentMode.FAST))
    assert len(deep.chunks) >= len(fast.chunks)


def test_non_retrievable_sections_never_enter_results(tmp_path) -> None:
    target = copy_profile(tmp_path)

    def hide(content: dict) -> None:
        section_by_id(content, "interests")["retrievable"] = False

    rewrite_profile(target, hide)
    result = ProfileRetriever().retrieve(
        load_profile_source(target), "Sample Sports Club taraftarı mı, hobileri neler?", language="tr",
        budget=budget_for_mode(AgentMode.DEEP_RESEARCH),
    )

    assert "interests" not in result.section_ids


def test_owner_name_alone_is_not_evidence() -> None:
    result = ProfileRetriever().retrieve(
        canonical_document(), "Sample Sample Author MrBekoX", language="tr", budget=budget_for_mode(AgentMode.FAST)
    )
    assert result.sufficient is False


def test_english_question_retrieves_turkish_section_via_aliases_a15() -> None:
    document = canonical_document()
    retriever = ProfileRetriever()
    budget = budget_for_mode(AgentMode.FAST)

    tr = retriever.retrieve(document, "Sample'ın eğitmenlik deneyimi nedir?", language="tr", budget=budget)
    en = retriever.retrieve(document, "What is Sample's teaching background?", language="en", budget=budget)

    assert tr.section_ids[0] == en.section_ids[0] == "teaching"


def test_query_cache_is_bounded() -> None:
    document = canonical_document()
    retriever = ProfileRetriever(cache_capacity=2)
    budget = budget_for_mode(AgentMode.FAST)
    for question in ("Vibeo nedir?", "Emojify nedir?", "Adhan Time nedir?"):
        retriever.retrieve(document, question, language="tr", budget=budget)

    assert len(retriever._results) == 2
    assert retriever.retrieve(document, "Vibeo nedir?", language="tr", budget=budget).cached is False
