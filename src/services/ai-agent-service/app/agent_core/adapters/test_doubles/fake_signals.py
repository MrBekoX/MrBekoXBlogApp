"""İptal ve ilerleme test double'ları."""

from __future__ import annotations

from ...errors import AgentErrorCode, PortError
from ...models import DomainProgress

__all__ = ["PreCancelledToken", "RecordingProgressSink", "StubCancellationToken"]


class StubCancellationToken:
    """Hiç iptal etmeyen test double."""

    is_test_double = True

    def is_cancelled(self) -> bool:
        return False

    def reason(self) -> str | None:
        return None

    def raise_if_cancelled(self) -> None:
        return None


class PreCancelledToken:
    """Zaten iptal edilmiş test double; ilk ``raise_if_cancelled`` çağrısında fırlatır."""

    is_test_double = True

    def __init__(self, reason: str = "test iptali") -> None:
        self._reason = reason

    def is_cancelled(self) -> bool:
        return True

    def reason(self) -> str | None:
        return self._reason

    def raise_if_cancelled(self) -> None:
        raise PortError(
            AgentErrorCode.CANCELLED,
            f"çalışma iptal edildi: {self._reason}",
            port="CancellationToken",
            retryable=False,
        )


class RecordingProgressSink:
    """Yayılan olayları listeleyen test double."""

    is_test_double = True

    def __init__(self, *, fail_with: PortError | None = None) -> None:
        self.events: list[DomainProgress] = []
        self.fail_with = fail_with

    async def publish(self, progress: DomainProgress) -> None:
        if self.fail_with is not None:
            raise self.fail_with
        self.events.append(progress)
