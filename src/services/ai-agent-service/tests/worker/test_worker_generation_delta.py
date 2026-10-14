"""Worker progress sink'inin ``GENERATION_DELTA`` köprüsü (streaming sözleşmesi).

Parçalı üretim metni ``publish_progress`` (seyrekleştirilen) yoluna DÜŞMEZ:
``publish_generation_delta``'ya köprülenir — yoksa throttle token akışını
kalıcı olarak yutardı. Bu dosya broker'sız birim testtir (kayıt eden
yayıncı double'ı); action_proposed yönlendirme testiyle aynı desendir.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from agent_core.models import DomainProgress, ProgressKind

from .helpers import run
from messaging.worker import _LeaseWatch, _WorkerProgressSink


class _FakeWatch:
    """Lease watch double: heartbeat gözlemlenir, lease kaybı yok."""

    is_test_double = True

    def __init__(self) -> None:
        self.beats = 0

    async def heartbeat(self) -> None:
        self.beats += 1


class _RecordingPublisher:
    """Üç yayın yöntemini ayırarak kaydeden double (B5 ``AgentEventPublisher``)."""

    is_test_double = True

    def __init__(self) -> None:
        self.progressed: list[dict[str, Any]] = []
        self.proposed: list[dict[str, Any]] = []
        self.deltas: list[dict[str, Any]] = []

    async def publish_progress(self, **kwargs: Any) -> Any:
        self.progressed.append(kwargs)
        return object()  # ThrottledProgress değil

    async def publish_action_proposed(self, **kwargs: Any) -> Any:
        self.proposed.append(kwargs)
        return object()

    async def publish_generation_delta(self, **kwargs: Any) -> list[Any]:
        self.deltas.append(kwargs)
        return [object()]


def _sink(publisher: Any) -> Any:
    return _WorkerProgressSink(
        run_id="2aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa2",
        conversation_id="3aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa3",
        correlation_id="4aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa4",
        causation_id="5aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa5",
        execution_attempt=1,
        publisher=publisher,
        watch=_FakeWatch(),
    )


def _progress(kind: ProgressKind, message: str) -> DomainProgress:
    return DomainProgress(
        run_id="2aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa2",
        kind=kind,
        message=message,
        occurred_at=datetime.now(timezone.utc),
    )


def test_generation_delta_routes_to_dedicated_publisher_not_progressed() -> None:
    publisher = _RecordingPublisher()
    sink = _sink(publisher)

    run(sink.publish(_progress(ProgressKind.GENERATION_DELTA, "Merhaba")))
    run(sink.publish(_progress(ProgressKind.GENERATION_DELTA, " dünya")))

    assert publisher.progressed == []  # seyrekleştirilen yola DÜŞMEZ
    assert publisher.proposed == []
    assert len(publisher.deltas) == 2
    first, second = publisher.deltas
    # Not: DomainProgress.message NonEmptyText boşlukları kırpar (mevcut domain
    # sözleşmesi); köprü metni aynen taşır, kırpım domain sınırındadır.
    assert first["text"] == "Merhaba"
    assert second["text"] == "dünya"
    assert first["execution_attempt"] == 1
    assert first["causation_id"] == "5aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa5"
    assert first["run_id"] == "2aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa2"
    assert first["conversation_id"] == "3aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa3"
    assert first["correlation_id"] == "4aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa4"
    # occurred_at domain olayından aynen taşınır
    assert first["occurred_at"] is not None


def test_other_kinds_still_route_to_progressed() -> None:
    """Köprü yalnız delta içindir: diğer kind'lar publish_progress yolunda kalır."""

    publisher = _RecordingPublisher()
    sink = _sink(publisher)

    run(sink.publish(_progress(ProgressKind.GENERATION_STARTED, "yanıt üretiliyor")))

    assert publisher.deltas == []
    assert len(publisher.progressed) == 1
    assert publisher.progressed[0]["kind"] == "generation_started"
    # detail transport'a taşınmaya devam eder (mevcut davranış korunur)
    run(sink.publish(DomainProgress(
        run_id="2aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa2",
        kind=ProgressKind.TOOL_ERROR,
        message="arama hatası",
        detail={"node": "research.search"},
        occurred_at=datetime.now(timezone.utc),
    )))
    assert publisher.progressed[1]["detail"] == {"node": "research.search"}
