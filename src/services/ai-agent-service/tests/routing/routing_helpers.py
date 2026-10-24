"""tests/routing yardımcıları (L005 kuralı: conftest.py DEĞİL, adlandırılmış modül).

``tests/`` alt dizinleri ``__init__.py``'li paket değildir; burada conftest.py
AÇILMAZ. Modül adı BENZERSİZ olmalıdır: ``tests/qa/helpers.py`` zaten
``helpers`` adıyla yüklendiğinden (rootdir-relative import modu) aynı adlı
ikinci modül tek pytest koşusunda çakışır — bu yüzden ad ``routing_helpers``.

Only deterministic routing inputs and event-loop helpers are defined here.
"""

from __future__ import annotations

import asyncio
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
