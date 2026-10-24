"""Published comparison/finding relations require more than lexical overlap."""

import asyncio
import json
from datetime import datetime, timezone

import pytest

from agent_core.budget.guard import BudgetGuard
from agent_core.budget.policy import BudgetPolicy, Deadline
from agent_core.budget.store import PolicyBudgetStore
from agent_core.errors import PortError
from agent_core.models import compute_content_hash
from agent_core.ports import BudgetKind, ModelResponse, ModelUsage
from agent_core.research.models import ClaimEvidenceRecord, ClaimRecord, SupportKind
from agent_core.research.semantic import _parse, semantic_coverage, verify_relations


def records():
    claim = ClaimRecord(claim_id="claim", article_id="article", article_revision=1,
        text="Requests may bypass authentication before accessing account data.", char_start=0, char_end=64)
    text = "Requests must not bypass authentication before accessing account data."
    record = ClaimEvidenceRecord(evidence_id="old-heuristic-id", claim_id=claim.claim_id,
        source_id="source", url="https://example.com/auth", excerpt=text, char_start=0, char_end=len(text),
        source_content_hash=compute_content_hash(text), support=SupportKind.SUPPORTS, rationale="Legacy word overlap")
    return claim, record


def test_semantic_contradiction_replaces_legacy_support_and_resolves_coverage():
    claim, record = records()

    class Model:
        async def complete(self, request, *, cancel):
            assert request.temperature is None
            return ModelResponse(text=json.dumps({"relations": [{"id": "R0", "relation": "contradicts", "quote": record.excerpt}]}),
                usage=ModelUsage(prompt_tokens=20, completion_tokens=10), finished_at=datetime.now(timezone.utc))

    async def scenario():
        policy = BudgetPolicy()
        guard = BudgetGuard(PolicyBudgetStore(policy), policy, "relation-test")
        checked, events, complete = await verify_relations(claims=[claim], evidence=[record], model=Model(),
                                                         guard=guard, deadline=Deadline(10))
        assert complete and checked[0].support is SupportKind.CONTRADICTS
        assert checked[0].evidence_id != record.evidence_id and events[0].total_tokens == 30
        uncovered, contradicted, unresolved = semantic_coverage([claim], checked, ["Can requests bypass auth?"])
        assert uncovered == set() and contradicted == {claim.claim_id} and unresolved == []
    asyncio.run(scenario())


@pytest.mark.parametrize("bad", [{"relations": []}, {"relations": [{"id": "R0", "relation": [], "quote": ""}]},
    {"relations": [{"id": "R99", "relation": "supports", "quote": "actual quote"}]}])
def test_relation_verifier_cannot_omit_change_or_malform_records(bad):
    claim, record = records()
    with pytest.raises(PortError):
        _parse(json.dumps(bad), [("R0", record)], {claim.claim_id: claim})


def test_support_requires_exact_external_quote_and_matching_numbers():
    claim, record = records()
    raw = json.dumps({"relations": [{"id": "R0", "relation": "supports", "quote": "invented but plausible quote"}]})
    checked = _parse(raw, [("R0", record)], {claim.claim_id: claim})
    assert checked[0].support is SupportKind.UNCLEAR


def test_budget_unavailability_never_promotes_legacy_lexical_support():
    claim, record = records()
    class MustNotCall:
        async def complete(self, *args, **kwargs): raise AssertionError("No model call may start")
    async def scenario():
        policy = BudgetPolicy(max_model_calls=1)
        store = PolicyBudgetStore(policy)
        guard = BudgetGuard(store, policy, "exhausted")
        reservation = await guard.reserve(BudgetKind.MODEL_CALL)
        await guard.commit(reservation, 1)
        checked, _, complete = await verify_relations(claims=[claim], evidence=[record], model=MustNotCall(), guard=guard)
        assert not complete and checked[0].support is SupportKind.UNCLEAR
    asyncio.run(scenario())
