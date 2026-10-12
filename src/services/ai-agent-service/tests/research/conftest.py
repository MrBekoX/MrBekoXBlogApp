"""tests/research yardımcıları ve gerçekçi fixture'lar.

L005 kuralı: bu dizin ``__init__.py``'li pakettir; conftest.py güvenlidir ve
testler ``from .conftest import ...`` ile yardımcıları alır (B4 intake deseni).

Gerçekçilik: web tarafı tests/web'in localhost ``MockWebServer``'ı üzerinden
GERÇEK HTTP ile çalışır (SSRF koruması, boyut/içerik türü sınırları devrede);
L005 kapsamında ``web`` test paketinin yardımcı modülü tüketilir, değiştirilmez
(A6 dosyaları yalnız tüketilir). Model/arama/iptal test double'ları yereldir;
tümü ``is_test_double`` işaretlidir ve double sonucu gerçek sağlayıcı başarısı
sayılmaz.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from agent_core.budget.guard import BudgetGuard
from agent_core.budget.policy import BudgetPolicy
from agent_core.budget.store import PolicyBudgetStore
from agent_core.errors import AgentErrorCode, PortError
from agent_core.models import (
    AgentMode,
    BudgetProfile,
    ExecutionContext,
    RouteDecision,
    RunIntent,
    compute_content_hash,
)
from agent_core.ports import CancellationToken, WebSearchResult
from web.web_helpers import MockResponse, MockWebServer, html_page, make_settings

NOW = datetime(2026, 10, 12, 12, 0, 0, tzinfo=timezone.utc)

QUESTION = "asyncio kuyruk sınırı ve hata yönetimi için güncel öneriler nelerdir?"

CLAIM_1 = "asyncio kuyruk sınırı için önerilen üst değer 1000'dir."
CLAIM_2 = "Kuyruk dolunca QueueFull istisnası fırlar; hata yönetimi try/except ile yapılmalıdır."

#: Makale: iki iddialı cümle; başlıklar ve kod blokları iddia değildir.
ARTICLE_CONTENT = (
    "# asyncio Kuyruk Rehberi\n\n"
    "## Kuyruk sınırı\n\n"
    f"{CLAIM_1}\n\n"
    "## Hata yönetimi\n\n"
    f"{CLAIM_2}\n"
)

#: Kaynak sayfa metinleri (MockWebServer gövdeleri).
GUIDE_TEXT = (
    "asyncio kuyruk sınırı için güncel öneri 1000 üst değeridir. "
    "Küçük kuyruklar bellek kullanımını düşürür."
)
#: İki cümle: ilki iddiayla sayısal çelişir (100 ≠ 1000).
CONFLICT_TEXT = "Önerilen kuyruk sınırı 100'dür. 1000 değeri aşırı beklemeye yol açabilir."
ERRORS_TEXT = (
    "Kuyruk dolunca QueueFull istisnası fırlar; hata yönetimi try/except bloğuyla yapılmalıdır."
)


def run(coroutine: Any) -> Any:
    """Coroutine'i pytest-asyncio olmadan senkron çalıştırır."""
    return asyncio.run(coroutine)


def make_research_snapshot(**overrides: Any):
    from agent_core.models import ArticleSnapshot

    content = overrides.pop("content", ARTICLE_CONTENT)
    defaults: dict[str, Any] = dict(
        article_id="post-queue",
        slug="asyncio-kuyruk-rehberi",
        title="asyncio Kuyruk Rehberi",
        content=content,
        content_hash=compute_content_hash(content),
        article_revision=7,
        language="tr",
        fetched_at=NOW,
    )
    defaults.update(overrides)
    return ArticleSnapshot(**defaults)


def make_research_context(snapshot: Any = None, **overrides: Any) -> ExecutionContext:
    if snapshot is None:
        snapshot = make_research_snapshot()
    defaults: dict[str, Any] = dict(
        run_id="run-research-1",
        conversation_id="conv-research-1",
        question=QUESTION,
        language="tr",
        mode_preference="deep_research",
        budget_profile=BudgetProfile(
            name="research-default",
            max_model_calls=4,
            max_total_tokens=120_000,
            max_tool_calls=24,
            max_web_search_calls=8,
            max_duration_seconds=120.0,
        ),
    )
    defaults.update(overrides)
    if snapshot is not None:
        defaults.setdefault("article_id", snapshot.article_id)
        defaults.setdefault("article_revision", snapshot.article_revision)
        defaults.setdefault("article_content_hash", snapshot.content_hash)
        defaults.setdefault("article_snapshot", snapshot)
    return ExecutionContext(**defaults)


def make_research_route(**overrides: Any) -> RouteDecision:
    defaults: dict[str, Any] = dict(
        run_id="run-research-1",
        selected_mode=AgentMode.DEEP_RESEARCH,
        intent=RunIntent.RESEARCH,
        needs_web=True,
        brief_reason="güncel dış kanıt gerektiren araştırma sorusu",
        decided_at=NOW,
    )
    defaults.update(overrides)
    return RouteDecision(**defaults)


def make_research_policy(**overrides: Any) -> BudgetPolicy:
    defaults: dict[str, Any] = dict(max_duration_seconds=60.0)
    defaults.update(overrides)
    return BudgetPolicy(**defaults)


# --- Model test double -------------------------------------------------------


class FixedModelProvider:
    """Sabit kısa sonuç döndüren model double'ı; istemler kaydedilir.

    ``fabricated_marker`` verilirse çıktıya uydurma kaynak kimliği ekler
    (kontrol düğümünün ayıklaması için).
    """

    is_test_double = True

    def __init__(self, text: str = "Kaynaklar kuyruk üst sınırını destekliyor.", *,
                 fabricated_marker: str | None = None) -> None:
        self._text = text
        self._fabricated = fabricated_marker
        self.requests: list[Any] = []
        self.call_count = 0

    async def complete(self, request: Any, *, cancel: Any = None) -> Any:
        from agent_core.ports import ModelResponse, ModelUsage

        if cancel is not None:
            cancel.raise_if_cancelled()
        self.requests.append(request)
        self.call_count += 1
        text = self._text
        if self._fabricated:
            text = f"{text} [{self._fabricated}]"
        return ModelResponse(
            text=text,
            model_name="fixed-model",
            usage=ModelUsage(prompt_tokens=20, completion_tokens=10),
            finished_at=datetime.now(timezone.utc),
        )


# --- Arama sağlayıcı test double ---------------------------------------------


class RoutingSearchProvider:
    """Sorgu alt dizisine göre sonuç döndüren senaryolu arama double'ı.

    ``routes``: (alt dizi, url listesi) — ilk eşleşen rota kazanır; hiçbiri
    eşleşmezse boş sonuç. Çağrılar ``calls`` listesine yazılır.
    """

    is_test_double = True

    def __init__(self, routes: list[tuple[str, list[str]]]) -> None:
        self.routes = list(routes)
        self.calls: list[str] = []

    async def search(
        self, query: str, *, max_results: int = 5, cancel: CancellationToken | None = None
    ) -> list[WebSearchResult]:
        if not query.strip():
            raise PortError(AgentErrorCode.VALIDATION_ERROR, "boş sorgu", port="RoutingSearchProvider")
        if cancel is not None:
            cancel.raise_if_cancelled()
        self.calls.append(query)
        for needle, urls in self.routes:
            if needle in query:
                return [
                    WebSearchResult(title=url.rsplit("/", 1)[-1] or url, url=url, retrieved_at=NOW)
                    for url in urls
                ][:max_results]
        return []


# --- İptal test double ---------------------------------------------------------


class CancelAfterToken:
    """Belirtilen sayıda ``raise_if_cancelled`` çağrısından sonra iptal olur."""

    is_test_double = True

    def __init__(self, after: int, reason: str = "ara ara iptali") -> None:
        self._after = after
        self._seen = 0
        self._reason = reason

    def is_cancelled(self) -> bool:
        return self._seen >= self._after

    def reason(self) -> str | None:
        return self._reason

    def raise_if_cancelled(self) -> None:
        self._seen += 1
        if self._seen > self._after:
            raise PortError(
                AgentErrorCode.CANCELLED,
                f"çalışma iptal edildi: {self._reason}",
                port="CancellationToken",
            )


# --- Mock HTTP sunucusu ve araç kümesi -----------------------------------------


def build_server(pages: dict[str, str], *, status_overrides: dict[str, int] | None = None) -> MockWebServer:
    """Sayfa metinlerinden mock HTTP sunucusu kurar (henüz başlatılmış değil)."""
    server = MockWebServer()
    overrides = status_overrides or {}
    for path, text in pages.items():
        status = overrides.get(path, 200)
        server.handlers[path] = MockResponse.html(html_page(text, title=path.strip("/").capitalize()), status=status)
    return server


def build_web_bundle(
    server: MockWebServer,
    provider: Any,
    *,
    policy: BudgetPolicy,
    run_id: str = "run-research-1",
) -> tuple[dict[str, Any], PolicyBudgetStore]:
    """A6 araç kümesini test bütçe deposuyla kurar; (web_tools, store) döner.

    Runner'a aynı ``store`` verilir; böylece araç rezervasyonları ile graph
    rezervasyonları ortak bütçeyi paylaşır (plan A7).
    """
    from agent_core.web import build_web_tools

    store = PolicyBudgetStore(policy)
    guard = BudgetGuard(store, policy, run_id)
    settings = make_settings(server, retry_backoff_base_s=0.0)
    tools = build_web_tools(guard, settings, search_provider=provider)
    return tools, store
