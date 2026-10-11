"""CheckpointStore portu.

Veri: LangGraph state checkpoint kayıt/okuma — A0 §5; somut kalıcılık A8'de
tanımlanır (Redis altyapısı transport tarafında mevcuttur, A0 §4). Payload
çekirdek tarafından serileştirilen opak bayt dizisidir; port içeriği çözümlemez.

Hata türleri: ``not_found`` (checkpoint yok), ``provider_error``, ``timeout``.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

__all__ = ["CheckpointStore"]


@runtime_checkable
class CheckpointStore(Protocol):
    """Run bazında checkpoint saklayan port."""

    async def save(self, run_id: str, checkpoint_id: str, payload: bytes) -> None:
        """Checkpoint'i yazar; aynı kimliğe yeniden yazma üzerine yazar."""
        ...

    async def load(self, run_id: str, checkpoint_id: str) -> bytes:
        """Belirli checkpoint'i okur.

        Raises:
            PortError: ``not_found`` — checkpoint bulunamadı;
                ``provider_error``/``timeout`` — depo arızası.
        """
        ...

    async def load_latest(self, run_id: str) -> tuple[str, bytes]:
        """Run'ın en son yazılan checkpoint'ini ``(checkpoint_id, payload)`` döndürür.

        Raises:
            PortError: ``not_found`` — run için checkpoint yok.
        """
        ...
