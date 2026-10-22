"""Who am I profil retrieval ölçümü (W7 offline; test double YOK, gerçek LLM YOK).

``evals/profile/questions.json`` kümesini GERÇEK canonical profil kaynağı ve
GERÇEK lexical retriever (``agent_core.profile``) ile koşar. Sorgu planı
runner'ın kendi ``plan_profile_query`` fonksiyonudur (politika çıkarımı,
who_am_i ziyaretçi dönüşümü, takip sorusu genişletme): ölçüm üretim yolunun
kopyası değildir.

Ölçülenler:

- retrieval hit@k: beklenen bölümlerden en az biri mod bütçesindeki top-k'da;
- precision@1: ilk parça beklenen bölümlerden biri mi; MRR;
- yetersiz-kanıt doğruluğu: kanıtı olmayan sorularda ``sufficient=False``;
- politika doğruluğu: beklenen kategoriler ve politika-yalnız kararı;
- routing doğruluğu: AUTO/who_am_i rota beklentileri (model çağrısı yok).

Bu bir LEXICAL retrieval ölçümüdür; anlamsal embedding veya gerçek model
kalite ölçümü DEĞİLDİR (gerçek sağlayıcı ölçümü ayrıca raporlanmalıdır).

Çalıştırma (hizmet kökünden)::

    python -m evals.profile_retrieval
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ._paths import ensure_service_paths

ensure_service_paths()

from agent_core.models import (  # noqa: E402
    AgentMode,
    BudgetProfile,
    ConversationTopic,
    ExecutionContext,
    ModePreference,
    RunIntent,
)
from agent_core.profile import (  # noqa: E402
    CanonicalProfileRepository,
    ProfileDocument,
    ProfileRetriever,
    budget_for_mode,
    is_visitor_identity_route,
    resolve_profile_dir,
)
from agent_core.profile.runner import plan_profile_query  # noqa: E402
from agent_core.routing import route_for_context  # noqa: E402

__all__ = ["QUESTIONS_PATH", "ProfileEvalReport", "load_cases", "measure", "route_case"]

QUESTIONS_PATH = Path(__file__).resolve().parent / "profile" / "questions.json"

#: Retrieval ölçümüne giren türler (beklenen bölüm taşıyanlar).
_RETRIEVAL_KINDS = frozenset({"retrieval", "policy", "policy_allowed", "injection"})


@dataclass
class CaseResult:
    case_id: str
    kind: str
    ok: bool
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProfileEvalReport:
    provider: str = "lexical_retriever (no model, no embedding)"
    retrieval_total: int = 0
    retrieval_hits: int = 0
    precision_at_1_hits: int = 0
    reciprocal_rank_sum: float = 0.0
    insufficient_total: int = 0
    insufficient_ok: int = 0
    policy_total: int = 0
    policy_ok: int = 0
    routing_total: int = 0
    routing_ok: int = 0
    results: list[CaseResult] = field(default_factory=list)

    @property
    def hit_rate(self) -> float:
        return self.retrieval_hits / self.retrieval_total if self.retrieval_total else 0.0

    @property
    def precision_at_1(self) -> float:
        return self.precision_at_1_hits / self.retrieval_total if self.retrieval_total else 0.0

    @property
    def mrr(self) -> float:
        return self.reciprocal_rank_sum / self.retrieval_total if self.retrieval_total else 0.0

    def failures(self) -> list[CaseResult]:
        return [result for result in self.results if not result.ok]

    def summary(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "retrieval_hit_rate": round(self.hit_rate, 4),
            "retrieval_hits": f"{self.retrieval_hits}/{self.retrieval_total}",
            "precision_at_1": round(self.precision_at_1, 4),
            "mrr": round(self.mrr, 4),
            "insufficient_correct": f"{self.insufficient_ok}/{self.insufficient_total}",
            "policy_correct": f"{self.policy_ok}/{self.policy_total}",
            "routing_correct": f"{self.routing_ok}/{self.routing_total}",
            "failures": [result.case_id for result in self.failures()],
        }


def load_cases(path: Path = QUESTIONS_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _topic(case: dict[str, Any]) -> ConversationTopic:
    return ConversationTopic(case.get("topic", "who_am_i"))


def _mode(case: dict[str, Any]) -> AgentMode:
    preference = case.get("mode_preference", "auto")
    return AgentMode.FAST if preference == "auto" else AgentMode(preference)


def _expected_categories(verdict) -> list[str]:
    categories = [*verdict.undisclosed, *verdict.unknown]
    if verdict.modification_request:
        categories.append("modification_request")
    if verdict.identity_claim:
        categories.append("identity_claim")
    return categories


def _context_for(case: dict[str, Any], document: ProfileDocument) -> ExecutionContext:
    topic = _topic(case)
    fields: dict[str, Any] = dict(
        run_id=f"eval-{case['id']}",
        conversation_id=f"eval-conv-{case['id']}",
        question=case["question"],
        language=case.get("language", "tr"),
        mode_preference=ModePreference(case.get("mode_preference", "auto")),
        budget_profile=BudgetProfile(name="eval", max_model_calls=4, max_total_tokens=20000, max_duration_seconds=60.0),
        conversation_topic=topic,
        profile_snapshot=document.snapshot,
    )
    if case.get("article_bound") and topic is not ConversationTopic.WHO_AM_I:
        fields.update(article_id="post-eval", article_revision=1)
        if case.get("selected_text"):
            fields["selected_text"] = case["selected_text"]
    return ExecutionContext(**fields)


def route_case(case: dict[str, Any], document: ProfileDocument) -> str:
    """Rota sınıfı: ``visitor_clarification`` | ``profile`` | ``not_profile`` (model çağrısı yok)."""

    decision = asyncio.run(route_for_context(_context_for(case, document)))
    if is_visitor_identity_route(decision):
        return "visitor_clarification"
    if decision.intent is RunIntent.PROFILE:
        assert decision.needs_web is False
        return "profile"
    return "not_profile"


def measure(
    cases_payload: dict[str, Any] | None = None,
    *,
    document: ProfileDocument | None = None,
    retriever: ProfileRetriever | None = None,
) -> ProfileEvalReport:
    """Kümeyi gerçek canonical kaynak + lexical retriever ile ölçer."""

    payload = cases_payload or load_cases()
    doc = document or CanonicalProfileRepository(resolve_profile_dir()).current_document()
    profile_retriever = retriever or ProfileRetriever()
    report = ProfileEvalReport()

    for case in payload["cases"]:
        kind = case["kind"]
        topic = _topic(case)
        if kind == "routing":
            report.routing_total += 1
            got = route_case(case, doc)
            ok = got == case["expected_route"]
            report.routing_ok += int(ok)
            report.results.append(CaseResult(case["id"], kind, ok, {"route": got}))
            continue

        plan = plan_profile_query(
            doc,
            question=case["question"],
            language=case.get("language", "tr"),
            topic=topic,
            previous_user_questions=list(case.get("history", [])),
            retriever=profile_retriever,
        )
        detail: dict[str, Any] = {"policy": _expected_categories(plan.verdict), "policy_only": plan.policy_only}
        ok = True

        # Runner ile aynı karar: plan politika-yalnız değilse ama kalan soru
        # kanıt bulamıyorsa yine deterministik politika cevabı verilir.
        policy_only = plan.policy_only
        if plan.verdict.flagged and not plan.policy_only:
            remainder_result = profile_retriever.retrieve(
                doc, plan.retrieval_query, language=plan.answer_language, budget=budget_for_mode(_mode(case))
            )
            policy_only = not remainder_result.sufficient
        detail["policy_only"] = policy_only

        if "expected_policy" in case:
            report.policy_total += 1
            policy_ok = sorted(_expected_categories(plan.verdict)) == sorted(case["expected_policy"])
            if "policy_only" in case:
                policy_ok = policy_ok and policy_only == case["policy_only"]
            report.policy_ok += int(policy_ok)
            ok = ok and policy_ok

        if kind == "insufficient":
            report.insufficient_total += 1
            result = profile_retriever.retrieve(
                doc, plan.retrieval_query, language=plan.answer_language, budget=budget_for_mode(_mode(case))
            )
            insufficient_ok = not result.sufficient and not plan.policy_only
            report.insufficient_ok += int(insufficient_ok)
            detail.update(top_score=result.top_score, sections=result.section_ids)
            report.results.append(CaseResult(case["id"], kind, insufficient_ok and ok, detail))
            continue

        expected = case.get("expected_sections")
        if kind in _RETRIEVAL_KINDS and expected and not policy_only:
            report.retrieval_total += 1
            result = profile_retriever.retrieve(
                doc, plan.retrieval_query, language=plan.answer_language, budget=budget_for_mode(_mode(case))
            )
            sections = [item.chunk.section_id for item in result.chunks]
            hit = result.sufficient and any(section in sections for section in expected)
            rank = next((index for index, section in enumerate(sections, start=1) if section in expected), None)
            report.retrieval_hits += int(hit)
            report.precision_at_1_hits += int(bool(sections) and sections[0] in expected)
            report.reciprocal_rank_sum += 1.0 / rank if rank else 0.0
            detail.update(sections=sections, top_score=result.top_score, sufficient=result.sufficient)
            ok = ok and hit
        report.results.append(CaseResult(case["id"], kind, ok, detail))
    return report


def main() -> None:  # pragma: no cover - CLI
    report = measure()
    print(json.dumps(report.summary(), ensure_ascii=False, indent=2))
    for failure in report.failures():
        print(f"FAIL {failure.case_id} ({failure.kind}): {failure.detail}")


if __name__ == "__main__":  # pragma: no cover
    main()
