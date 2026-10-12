"""tests/routing yardımcıları (L005 kuralı: conftest.py DEĞİL, adlandırılmış modül).

``tests/`` alt dizinleri ``__init__.py``'li paket değildir; burada conftest.py
AÇILMAZ. Modül adı BENZERSİZ olmalıdır: ``tests/qa/helpers.py`` zaten
``helpers`` adıyla yüklendiğinden (rootdir-relative import modu) aynı adlı
ikinci modül tek pytest koşusunda çakışır — bu yüzden ad ``routing_helpers``.

Router modeli double'ları GERÇEK LLM DEĞİLDİR (is_test_double); öneri
doğrulama/politika eşleme davranışı yalnız yapılandırılmış çıktı sözleşmesi
üzerinden test edilir.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any

NOW = datetime(2026, 10, 12, 9, 0, 0, tzinfo=timezone.utc)


def run(coroutine: Any) -> Any:
    """Coroutine'i pytest-asyncio olmadan senkron çalıştırır."""
    return asyncio.run(coroutine)


def make_context(**overrides: Any):
    from agent_core.models import BudgetProfile, ExecutionContext

    defaults: dict[str, Any] = dict(
        run_id="run-route-1",
        conversation_id="conv-route-1",
        question="Kuyruk sınırı nasıl ayarlanır?",
        language="tr",
        mode_preference="auto",
        budget_profile=BudgetProfile(
            name="router-profile",
            max_model_calls=4,
            max_total_tokens=60000,
            max_duration_seconds=120.0,
        ),
    )
    defaults.update(overrides)
    return ExecutionContext(**defaults)


def suggestion_json(**fields: Any) -> str:
    """Router modelinin ürettiği yapılandırılmış öneri JSON'u; alanlar geçersizilebilir."""
    payload: dict[str, Any] = {
        "intent": "article_qa",
        "selected_mode": "fast",
        "needs_web": False,
        "needs_clarification": False,
        "clarification_question": None,
        "brief_reason": "test önerisi",
    }
    payload.update(fields)
    return json.dumps(payload, ensure_ascii=False)


class ScriptedRouterModel:
    """Çağrı sırasına göre hazır JSON yanıt döndüren router modeli double'ı.

    İstemler ``requests`` listesine yazılır; liste tükenirse test kırılır
    (sessiz varsayılan yanıt üretilmez).
    """

    is_test_double = True

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.requests: list[Any] = []
        self.call_count = 0

    async def complete(self, request: Any, *, cancel: Any = None) -> Any:
        from agent_core.ports import ModelResponse, ModelUsage
        from datetime import datetime, timezone

        if cancel is not None:
            cancel.raise_if_cancelled()
        self.requests.append(request)
        self.call_count += 1
        if not self._responses:
            raise AssertionError("ScriptedRouterModel yanıtı tükendi: beklenmedik router çağrısı")
        return ModelResponse(
            text=self._responses.pop(0),
            model_name="scripted-router",
            usage=ModelUsage(prompt_tokens=20, completion_tokens=10),
            finished_at=datetime.now(timezone.utc),
        )


class ExplodingRouterModel:
    """Kesin kararlarda router modelinin çağrilmamasını kanıtlayan double."""

    is_test_double = True

    def __init__(self) -> None:
        self.call_count = 0

    async def complete(self, request: Any, *, cancel: Any = None) -> Any:
        self.call_count += 1
        raise AssertionError(
            "ExplodingRouterModel çağrıldı: kesin kararda router modeli sorulmamalı"
        )


class FailingRouterModel:
    """Verilen PortError'ı fırlatan router modeli double'ı (arıza yolları)."""

    is_test_double = True

    def __init__(self, error: Any) -> None:
        self._error = error
        self.call_count = 0

    async def complete(self, request: Any, *, cancel: Any = None) -> Any:
        self.call_count += 1
        raise self._error
