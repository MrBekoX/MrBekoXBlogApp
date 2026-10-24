"""Production research composition and fail-closed dispatch; no network calls."""

import asyncio
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agent_core.budget.guard import BudgetGuard
from agent_core.budget.policy import BudgetPolicy
from agent_core.budget.store import PolicyBudgetStore
from agent_core.entrypoints import PreparedRun, execute_plan
from agent_core.errors import AgentErrorCode, PortError
from agent_core.models import AgentMode, BudgetProfile, ExecutionContext, RouteDecision, RunStatus, compute_content_hash
from agent_core.web.config import research_tools_from_env
from agent_core.web.search import HttpWebSearchProvider
from agent_core.ports import BudgetKind


@pytest.mark.parametrize("disabled_budget", [False, True])
def test_missing_research_capability_never_calls_a_model_or_claims_a_completed_report(disabled_budget):
    context = ExecutionContext(run_id="research-run", conversation_id="research-conversation",
        question="Research this article in depth", language="en", mode_preference="deep_research",
        budget_profile=BudgetProfile(name="test", max_model_calls=2, max_total_tokens=20000,
                                     max_duration_seconds=30), article_id="article-1", article_revision=1,
        article_content_hash=compute_content_hash("content"))
    route = RouteDecision(run_id=context.run_id, selected_mode=AgentMode.DEEP_RESEARCH,
        reason="Explicit research request", requires_web_search=True, decided_at=datetime.now(timezone.utc))
    prepared = PreparedRun(context=context, route=route, prepared_at=datetime.now(timezone.utc))

    class MustNotCall:
        async def stream_complete(self, *args, **kwargs):
            raise AssertionError("Unconfigured research must not invoke a model")

    tools = research_tools_from_env({"AGENT_WEB_SEARCH_URL": "https://search.example/api"}) if disabled_budget else None
    outcome = asyncio.run(execute_plan(prepared, model=MustNotCall(), web_tools=tools))
    assert outcome.status is RunStatus.FAILED
    assert outcome.error_code is (AgentErrorCode.BUDGET_EXHAUSTED if disabled_budget else AgentErrorCode.CONFIG_ERROR)
    assert outcome.report is None and outcome.answer is None
    assert outcome.usage.model_calls == 0


@pytest.mark.parametrize("url", ["http://search.example", "https://user:secret@search.example",
    "https://search.example?q=secret", "https://search.example#secret", "https://search.example:80"])
def test_research_endpoint_rejects_unsafe_configuration_without_logging_it(url):
    with pytest.raises(PortError) as raised:
        research_tools_from_env({"AGENT_WEB_SEARCH_URL": url})
    assert raised.value.code is AgentErrorCode.CONFIG_ERROR
    assert "secret" not in str(raised.value)


def test_research_tools_use_separate_run_budgets(monkeypatch):
    async def search(self, query, *, max_results=5, cancel=None):
        return []
    monkeypatch.setattr(HttpWebSearchProvider, "search", search)
    factory = research_tools_from_env({"AGENT_WEB_SEARCH_URL": "https://search.example/api"})
    assert research_tools_from_env({}) is None
    policy = BudgetPolicy()
    first = BudgetGuard(PolicyBudgetStore(policy), policy, "first")
    second = BudgetGuard(PolicyBudgetStore(policy), policy, "second")

    async def scenario():
        await factory(first)["search_web"].search("bounded research")
        assert (await first.usage()).committed[BudgetKind.WEB_SEARCH_CALL] == 1
        assert (await second.usage()).committed.get(BudgetKind.WEB_SEARCH_CALL, 0) == 0
        await factory(second)["search_web"].search("independent research")
        assert (await second.usage()).committed[BudgetKind.WEB_SEARCH_CALL] == 1
    asyncio.run(scenario())


@pytest.mark.parametrize("search_enabled", [False, True])
def test_production_composition_actually_binds_research_tools(monkeypatch, tmp_path, search_enabled):
    from app.service_main import _compose_components
    from agent_core.adapters import EmbeddingProviderSettings, LlmProviderSettings, OpenAiEmbeddingProvider, OpenAiModelProvider
    from agent_core.adapters.http_content_repository import ContentRepositorySettings, HttpContentRepository
    from agent_core.profile import CanonicalProfileRepository
    from messaging.db import AgentDbSettings
    from messaging.settings import BrokerSettings

    class EmptyPool:
        async def fetch(self, *args):
            return []

    monkeypatch.chdir(tmp_path)
    settings = EmbeddingProviderSettings(api_key="test-only-not-a-real-key")
    profile = CanonicalProfileRepository(Path(__file__).resolve().parents[3] / "content" / "author-profile")
    components = asyncio.run(_compose_components(db_settings=AgentDbSettings(), broker=BrokerSettings(),
        env={"AGENT_WEB_SEARCH_URL": "https://search.example/api"} if search_enabled else {}, pool=EmptyPool(),
        resolved_model=OpenAiModelProvider(LlmProviderSettings(api_key="test-only", model="test-only")),
        settings=settings, raw_embedding=OpenAiEmbeddingProvider(settings),
        resolved_content=HttpContentRepository(ContentRepositorySettings("http://backend/api/v1", "test-only")),
        resolved_profile=profile))
    assert callable(components.worker._deps.web_tools) is search_enabled
    assert components.worker._settings.budget_profile.max_web_search_calls == (8 if search_enabled else 0)
    assert components.worker._settings.budget_profile.max_tool_calls == 24


def test_zero_external_budget_is_not_increased_by_flow_overrides():
    from agent_core.qa.runner import qa_policy_for
    from agent_core.qa.models import QaFlowConfig
    profile = BudgetProfile(name="disabled-web", max_model_calls=2, max_total_tokens=8000, max_duration_seconds=30)
    policy = BudgetPolicy.from_budget_profile(profile, max_search_calls=8, max_source_pages=12,
                                             max_model_calls=100, max_total_tokens=999999, max_duration_seconds=600)
    assert policy.max_search_calls == policy.max_source_pages == 0
    assert policy.max_model_calls == 2 and policy.max_total_tokens == 8000 and policy.max_duration_seconds == 30
    # Internal article retrieval remains possible without granting network tools.
    qa = qa_policy_for(profile, QaFlowConfig())
    assert qa.max_tool_attempts > 0 and qa.max_search_calls == qa.max_source_pages == 0
