"""Optional production research tools, bound to each run's own budget.

An absent search endpoint means research is unavailable. Configuration never
performs a request and never substitutes an ungrounded model completion.
"""

from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import urlsplit

from ..budget.guard import BudgetGuard
from ..errors import AgentErrorCode, PortError
from .search import HttpWebSearchProvider
from .settings import WebToolSettings
from .ssrf import UrlGuard
from .tools import WebTools, build_web_tools


def research_tools_from_env(environ: Mapping[str, str]) -> WebTools | None:
    endpoint = environ.get("AGENT_WEB_SEARCH_URL", "").strip()
    if not endpoint:
        return None
    try:
        parsed = urlsplit(endpoint)
        valid = (
            parsed.scheme == "https" and bool(parsed.hostname)
            and parsed.username is None and parsed.password is None
            and not parsed.query and not parsed.fragment
            and parsed.port in (None, 443)
        )
    except ValueError:
        valid = False
    if not valid:
        raise PortError(
            AgentErrorCode.CONFIG_ERROR,
            "AGENT_WEB_SEARCH_URL must be an HTTPS endpoint without credentials, query or fragment",
            port="research_configuration",
        )
    settings = WebToolSettings(environment="production")
    # Credentials are read only by the search adapter, for this endpoint. The
    # source reader never receives them. UrlGuard also checks resolved addresses.
    provider = HttpWebSearchProvider(
        endpoint, settings, UrlGuard.from_settings(settings),
        api_key_env="AGENT_WEB_SEARCH_API_KEY" if environ.get("AGENT_WEB_SEARCH_API_KEY", "").strip() else None,
    )

    def bind(guard: BudgetGuard) -> dict[str, object]:
        return build_web_tools(guard, settings, search_provider=provider)

    return bind
