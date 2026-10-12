"""Bütçe politikası ve deadline (plan A2).

Başlangıç araştırma sınırları plan önerisidir ve yapılandırılabilir: 4 alt
soru, 8 arama çağrısı, 12 kaynak sayfası, ilk tur dahil 2 araştırma turu,
3 eşzamanlı alt görev; toplam token, toplam araç denemesi ve süre ayrı
sınırlardır. ``BudgetPolicy.from_budget_profile`` ExecutionContext'in
sunucu onaylı ``BudgetProfile``'ını politika üst sınırı olarak alır: profil
profili aşan politika değeri profille kısıtlanır.

``Deadline`` süre kontrolünün tek noktasıdır; node ve araç çağrısı sınırlarında
``raise_if_exceeded`` ile denetlenir (plan A2: "İptal ve deadline kontrollerini
node ve araç çağrısı sınırlarına koy").
"""

from __future__ import annotations

import time
from collections.abc import Callable

from pydantic import PositiveFloat, PositiveInt

from ..errors import AgentErrorCode, PortError
from ..models import BusinessModel, BudgetProfile

__all__ = ["BudgetPolicy", "Deadline"]


class BudgetPolicy(BusinessModel):
    """Yapılandırılabilir bütçe sınırları; varsayılanlar plan A2 önerisidir."""

    # Araştırma sınırları (plan önerisi).
    max_sub_questions: PositiveInt = 4
    max_search_calls: PositiveInt = 8
    max_source_pages: PositiveInt = 12
    max_research_rounds: PositiveInt = 2
    max_parallel_subtasks: PositiveInt = 3

    # Toplam sınırlar (yapılandırılabilir).
    max_model_calls: PositiveInt = 16
    max_total_tokens: PositiveInt = 200_000
    max_tool_attempts: PositiveInt = 24
    max_duration_seconds: PositiveFloat = 300.0

    # Sınırlı retry: tek eylem için en fazla deneme (ilk deneme dahil).
    max_attempts_per_action: PositiveInt = 2

    @classmethod
    def from_budget_profile(cls, profile: BudgetProfile, **overrides) -> "BudgetPolicy":
        """Sunucu bütçe profilini politika üst sınırı olarak birleştirir.

        Profilin koyduğu sınır politika varsayımından güçlüdür; araştırma
        sınırları profil taşımaz, varsayılan kalır.
        """
        merged = dict(
            max_model_calls=profile.max_model_calls,
            max_total_tokens=profile.max_total_tokens,
            max_tool_attempts=max(profile.max_tool_calls, 1),
            max_search_calls=max(profile.max_web_search_calls, 1),
            max_duration_seconds=profile.max_duration_seconds,
        )
        merged.update(overrides)
        return cls(**merged)


class Deadline:
    """Monotonik saatle çalışan süre sınırı; süreç saati kaymalarından bağımsızdır."""

    def __init__(self, seconds: float, *, clock: Callable[[], float] | None = None) -> None:
        if seconds <= 0:
            raise ValueError("deadline süresi pozitif olmalıdır")
        self._clock = clock or time.monotonic
        self._started_at = self._clock()
        self._budget_seconds = seconds

    def elapsed(self) -> float:
        return max(self._clock() - self._started_at, 0.0)

    def remaining(self) -> float:
        return max(self._budget_seconds - self.elapsed(), 0.0)

    @property
    def expired(self) -> bool:
        return self.remaining() <= 0.0

    def raise_if_exceeded(self) -> None:
        """Süre dolduysa ``PortError(TIMEOUT)`` fırlatır; retry edilmez.

        Raises:
            PortError: ``timeout`` — kalan süre yok.
        """
        if self.expired:
            raise PortError(
                AgentErrorCode.TIMEOUT,
                f"süre sınırı doldu: {self._budget_seconds:g}s (geçen {self.elapsed():.3f}s)",
                port="Deadline",
            )
