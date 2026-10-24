"""Production tool factories retain usage when a later research node fails."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from agent_core.errors import AgentErrorCode, PortError
from agent_core.models import BudgetProfile, ExecutionContext
from agent_core.research.runner import run_deep_research
from agent_core.web.config import research_tools_from_env
from agent_core.web.models import FetchedContent


@pytest.mark.parametrize("cancel_after_tools", [False, True])
def test_factory_bound_search_and_read_usage_survives_later_failure(monkeypatch, cancel_after_tools):
    async def search(_self, query, **kwargs):
        return []

    async def fetch(_self, url, **kwargs):
        return FetchedContent(requested_url=url, final_url=url, status_code=200,
                              content_type="text/html", body=b"<p>Verified source content.</p>",
                              fetched_at=datetime.now(timezone.utc))

    monkeypatch.setattr("agent_core.web.search.HttpWebSearchProvider.search", search)
    monkeypatch.setattr("agent_core.web.fetch.HttpFetcher.fetch", fetch)

    def build_graph(deps):
        class Graph:
            async def ainvoke(self, initial):
                # Real production wrappers use their own local event sink.
                # The runner's per-guard journal must still see this work.
                local_events = []
                await deps.tools["search_web"].search("queue sizing", events_sink=local_events)
                await deps.tools["read_source"].read("https://example.com/source", events_sink=local_events)
                assert len(local_events) == 2
                assert deps.tasks.take_events() == []
                if cancel_after_tools:
                    raise asyncio.CancelledError()
                raise PortError(AgentErrorCode.PROVIDER_ERROR, "A later research node failed")

        return Graph()

    monkeypatch.setattr("agent_core.research.runner.build_deep_research_graph", build_graph)
    context = ExecutionContext(run_id="journal-run", conversation_id="journal-conversation",
                               question="Research queue sizing", language="en",
                               budget_profile=BudgetProfile(name="test", max_web_search_calls=2,
                                                            max_tool_calls=4, max_duration_seconds=30,
                                                            max_model_calls=2, max_total_tokens=8000))
    factory = research_tools_from_env({"AGENT_WEB_SEARCH_URL": "https://search.example.com/query"})
    assert factory is not None
    result = asyncio.run(run_deep_research(context, None, model=None, web_tools=factory))
    assert result.outcome.status.value == ("cancelled" if cancel_after_tools else "failed")
    assert result.outcome.usage.web_search_calls == 1
    events = result.state["usage_events"]
    assert [event.kind.value for event in events] == ["web_search_call", "source_page_read"]
    assert len({event.event_id for event in events}) == 2
