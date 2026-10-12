"""BudgetGuard: çağrı öncesi rezervasyon, sonrası kullanım kaydı, sınırlı retry.

Tek giriş ``guarded``'dır: her dış çağrı için (1) iptal/deadline denetimi,
(2) atomik rezervasyon, (3) çağrı, (4) kullanım olayı akışı uygulanır. Üretilen
``UsageEvent``'ler node çıktısıyla state'e mergeslenir; ``event_id =
action_id#attempt`` olduğundan tekrar yürütme kopya kullanım üretmez, retry ise
yeni deneme olarak bütçeye yazılır.

Hata akışı (plan A2):
- ``budget_exhausted`` → rezervasyon reddedildi, çağrı başlamadı; olay üretilmez.
- retry edilebilir arıza (``retryable=True``) → çağrı rezervasyonu commit
  (deneme bütçeyi tüketti), token rezervasyonu release; deneme olayı
  ``outcome="failed"``; politika sınırı ve kalan süre dahilinde tekrar denenir.
- iptal (``CANCELLED`` veya ``asyncio.CancelledError``) → dış çağrının
  gerçekleşip gerçekleşmediği bilinmediğinden ``uncertain=True`` olayı yazılır,
  rezervasyonlar ihtiyatla commit edilir ve istisna bastırılmadan yükselir
  [PY-ASYNCIO#C2].
- sağlayıcı kullanım bilgisi yoksa token tahmini ``estimated=True`` yazılır.

MODEL_CALL için token rezervasyonu, toplam token bütçesinin çağrı başına
dilimidir (``max_total_tokens // max_model_calls``); paralel model çağrıları
kendi dilimini rezerve eder, ortak bütçe aşılırsa fazlası ``budget_exhausted``
ile çağrı öncesinde reddedilir. Tahmini dilim aşılırsa gerçek kullanım
commit edilir (kullanım zaten gerçekleşmiştir); birikimli aşım sonraki
rezervasyonların reddiyle görünür.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from ..errors import AgentErrorCode, PortError
from ..ports import BudgetKind, BudgetReservation, BudgetStore, BudgetUsage, CancellationToken
from ..ports.model import ModelUsage
from .policy import BudgetPolicy, Deadline

if TYPE_CHECKING:
    from ..state.events import UsageEvent

__all__ = [
    "BudgetGuard",
    "CallResult",
    "GuardedOutcome",
    "assert_active",
    "estimate_tokens",
]

#: Token tahmini için karakter başına oran (kaba; sonuç ``estimated`` işaretlidir).
_CHARS_PER_TOKEN = 4.0

#: Retryden önce kalan süre bu eşiğin altındaysa denenmez (saniye).
_MIN_RETRY_SECONDS = 0.05


def estimate_tokens(text: str) -> int:
    """Metin uzunluğundan kaba token tahmini üretir; tahmin işaretlemesi çağıranındır."""
    return max(int(math.ceil(len(text) / _CHARS_PER_TOKEN)), 1)


def assert_active(cancel: CancellationToken | None, deadline: Deadline | None) -> None:
    """Node ve araç çağrısı sınırlarındaki ortak canlılık kontrolü.

    Raises:
        PortError: ``cancelled`` — iptal sinyali; ``timeout`` — süre doldu.
    """
    if deadline is not None:
        deadline.raise_if_exceeded()
    if cancel is not None:
        cancel.raise_if_cancelled()


@dataclass
class CallResult:
    """Tek dış çağrının sonucu: taşıdığı değer ve sağlayıcı kullanımı.

    ``usage=None`` araç sınıfı çağrılarda normaldir (token bilgisi yok);
    MODEL_CALL'da ``usage=None`` veya sıfır token tahminle işaretlenir.
    """

    value: Any = None
    usage: ModelUsage | None = None


@dataclass
class GuardedOutcome:
    """``guarded`` çağrısının sonucu: değer + kullanım + state'e mergeslenecek olaylar."""

    value: Any
    usage: ModelUsage | None
    estimated: bool
    attempts: int
    events: list["UsageEvent"] = field(default_factory=list)


class BudgetGuard:
    """BudgetStore üzerinden rezervasyon ve kullanım kaydını yürüten yardımcı."""

    def __init__(self, store: BudgetStore, policy: BudgetPolicy, run_id: str) -> None:
        self._store = store
        self._policy = policy
        self._run_id = run_id

    @property
    def policy(self) -> BudgetPolicy:
        return self._policy

    async def reserve(self, kind: BudgetKind, amount: int = 1) -> BudgetReservation:
        return await self._store.reserve(self._run_id, kind, amount)

    async def commit(self, reservation: BudgetReservation, actual_amount: int) -> None:
        await self._store.commit(reservation, actual_amount)

    async def release(self, reservation: BudgetReservation) -> None:
        await self._store.release(reservation)

    async def usage(self) -> BudgetUsage:
        return await self._store.usage(self._run_id)

    async def track(self, kind: BudgetKind, action_id: str, *, amount: int = 1) -> list["UsageEvent"]:
        """Dış çağrı olmayan yönetimsel birimi (ör. araştırma turu) bütçeye yazar.

        Rezervasyon + commit tek adımda yapılır; sınır aşarsa
        ``PortError(BUDGET_EXHAUSTED)`` yükselir.

        Raises:
            PortError: ``budget_exhausted`` — birim bütçesi doldu.
        """
        reservation = await self.reserve(kind, amount)
        await self.commit(reservation, amount)
        return [self._event(action_id=action_id, kind=kind, attempt=1, outcome="success")]

    def _event(
        self,
        *,
        action_id: str,
        kind: BudgetKind,
        attempt: int,
        outcome: str,
        usage: ModelUsage | None = None,
        estimated: bool = False,
        uncertain: bool = False,
    ) -> "UsageEvent":
        from ..state.events import UsageEvent, UsageEventKind

        prompt = usage.prompt_tokens if usage is not None else 0
        completion = usage.completion_tokens if usage is not None else 0
        return UsageEvent(
            event_id=f"{action_id}#{attempt}",
            run_id=self._run_id,
            action_id=action_id,
            kind=UsageEventKind(kind.value),
            attempt=attempt,
            outcome=outcome,
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=prompt + completion,
            estimated=estimated,
            uncertain=uncertain,
            recorded_at=datetime.now(timezone.utc),
        )

    async def guarded(
        self,
        *,
        action_id: str,
        kind: BudgetKind,
        call: Callable[[int], Awaitable[CallResult]],
        cancel: CancellationToken | None = None,
        deadline: Deadline | None = None,
        token_estimate: int | None = None,
        events_sink: list["UsageEvent"] | None = None,
    ) -> GuardedOutcome:
        """Dış çağrıyı rezervasyon + kullanım kaydı + sınırlı retry ile yürütür.

        ``call(attempt)`` çalıştırılabilir dış çağrıdır; iptal ve deadline
        denetimi her denemenin başında ve çağrı sınırlarında yapılır.
        ``events_sink`` verilirse olaylar istisna yollarında da listeye yazılır
        (kesinti anında belirsiz kullanımın state'e ulaşması için).

        Raises:
            PortError: ``budget_exhausted`` — rezervasyon reddi (çağrı başlamaz);
                ``cancelled``/``timeout`` — canlılık kontrolleri; retry sınırı
                dolan son ``provider_error``/``timeout``.
        """
        events: list[UsageEvent] = []
        max_attempts = self._policy.max_attempts_per_action
        for attempt in range(1, max_attempts + 1):
            assert_active(cancel, deadline)  # çağrı öncesi: dış etki başlamadı
            call_reservation = await self.reserve(kind)
            token_reservation: BudgetReservation | None = None
            if kind is BudgetKind.MODEL_CALL:
                per_call = max(self._policy.max_total_tokens // max(self._policy.max_model_calls, 1), 1)
                token_reservation = await self.reserve(BudgetKind.TOKEN, token_estimate or per_call)
            try:
                result = await call(attempt)
            except PortError as error:
                if error.code is AgentErrorCode.CANCELLED:
                    await self._record_interruption(
                        action_id=action_id, kind=kind, attempt=attempt,
                        call_reservation=call_reservation, token_reservation=token_reservation,
                    )
                    self._emit(
                        events, events_sink,
                        self._event(action_id=action_id, kind=kind, attempt=attempt,
                                    outcome="uncertain", uncertain=True, estimated=True),
                    )
                    raise
                if error.code is AgentErrorCode.BUDGET_EXHAUSTED:
                    await self.release(call_reservation)
                    raise
                # Başarısız deneme bütçeyi tüketti: çağrı commit, token release.
                await self.commit(call_reservation, 1)
                if token_reservation is not None:
                    await self.release(token_reservation)
                self._emit(
                    events, events_sink,
                    self._event(action_id=action_id, kind=kind, attempt=attempt, outcome="failed"),
                )
                if error.retryable and attempt < max_attempts:
                    if deadline is None or deadline.remaining() > _MIN_RETRY_SECONDS:
                        continue
                raise
            except asyncio.CancelledError:
                await self._record_interruption(
                    action_id=action_id, kind=kind, attempt=attempt,
                    call_reservation=call_reservation, token_reservation=token_reservation,
                )
                self._emit(
                    events, events_sink,
                    self._event(action_id=action_id, kind=kind, attempt=attempt,
                                outcome="uncertain", uncertain=True, estimated=True),
                )
                raise

            usage = result.usage
            estimated = False
            if kind is BudgetKind.MODEL_CALL:
                if usage is None or usage.total_tokens == 0:
                    usage = ModelUsage(prompt_tokens=estimate_tokens(action_id), completion_tokens=0)
                    estimated = True  # sağlayıcı kullanım bilgisi yok: tahmin
                assert token_reservation is not None
                await self.commit(token_reservation, max(usage.total_tokens, 1))
            elif token_reservation is not None:  # pragma: no cover - yalnız MODEL_CALL açar
                await self.release(token_reservation)
            await self.commit(call_reservation, 1)
            self._emit(
                events, events_sink,
                self._event(action_id=action_id, kind=kind, attempt=attempt,
                            outcome="success", usage=usage, estimated=estimated),
            )
            return GuardedOutcome(
                value=result.value,
                usage=usage,
                estimated=estimated,
                attempts=attempt,
                events=events,
            )
        raise PortError(  # pragma: no cover - döngü her yolda döner veya yükselir
            AgentErrorCode.PROVIDER_ERROR,
            f"retry sınırı aşıldı: {action_id}",
            port="BudgetGuard",
        )

    @staticmethod
    def _emit(
        events: list["UsageEvent"],
        sink: list["UsageEvent"] | None,
        event: "UsageEvent",
    ) -> None:
        """Olayı hem dönüş listesine hem varsa dış akışa yazar."""
        events.append(event)
        if sink is not None:
            sink.append(event)

    async def _record_interruption(
        self,
        *,
        action_id: str,
        kind: BudgetKind,
        attempt: int,
        call_reservation: BudgetReservation,
        token_reservation: BudgetReservation | None,
    ) -> None:
        """Kesinti anında rezervasyonları ihtiyatla tüketir (belirsiz kullanım)."""
        await self.commit(call_reservation, 1)
        if token_reservation is not None:
            await self.commit(token_reservation, token_reservation.reserved_amount)
