"""Deterministic profile indexing, version, filtering, and cache checks."""

from __future__ import annotations


from profile_helpers import canonical_document, copy_profile, rewrite_profile, section_by_id

from agent_core.models import AgentMode
from agent_core.profile import (
    MODE_RETRIEVAL_BUDGETS,
    ProfileRetriever,
    budget_for_mode,
    load_profile_source,
)


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
    document = canonical_document()
    result = ProfileRetriever().retrieve(
        document, " ".join([document.owner.name, *document.owner.aliases]),
        language="tr", budget=budget_for_mode(AgentMode.FAST)
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
