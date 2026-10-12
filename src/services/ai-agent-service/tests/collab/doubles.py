"""B9 test double'ları: kayıt tutan resume driver'ı (``is_test_double`` kuralı).

Test double'lar üretim koduna sızmaz; yalnız bu pakette kullanılır (D009
ayrımı: double'lar açıkça işaretlidir).
"""

from __future__ import annotations

from typing import Any


class RecordingResumeDriver:
    """Driver çağrılarını kaydeden test double'ı: teslim → graph devamı sözleşmesi.

    ``graph`` verildiyse ``action_result`` çağrısı GERÇEK A9 çalışma makinesini
    (``run_collaboration``) doğrulanmış ``ValidatedActionResult`` ile sürdürür —
    kontrol tesliminin graph'ı gerçekten ilerlettiğinin kanıtı. Verilmediyse
    yalnız kayıt tutar (consumer sözleşmesi testleri).
    """

    is_test_double = True

    def __init__(self, *, fail_on_call: int | None = None, graph: Any | None = None) -> None:
        self.calls: list[tuple[str, str, Any]] = []  # (kind, run_id, payload)
        self.outcomes: list[dict[str, Any]] = []
        self.fail_on_call = fail_on_call
        self.graph = graph

    async def resume_requested(self, *, run_id: str, payload: Any) -> dict[str, Any]:
        return await self._record("resume_requested", run_id, payload)

    async def action_result(self, *, run_id: str, payload: Any) -> dict[str, Any]:
        return await self._record("action_result", run_id, payload)

    async def _record(self, kind: str, run_id: str, payload: Any) -> dict[str, Any]:
        self.calls.append((kind, run_id, payload))
        if self.fail_on_call is not None and len(self.calls) == self.fail_on_call:
            raise RuntimeError("driver bilinçli başarısız (test senaryosu)")
        if self.graph is not None:
            outcome = await self.graph(kind, run_id, payload)
            self.outcomes.append(outcome)
            if isinstance(outcome, dict):
                return outcome
            return {"stage": str(outcome.status.value if hasattr(outcome.status, "value") else outcome.status)}
        return {"outcome": "recorded"}

    @property
    def call_count(self) -> int:
        return len(self.calls)
