"""B2 broker modülü hata türleri."""

from __future__ import annotations

__all__ = ["TopologyError"]


class TopologyError(RuntimeError):
    """Pasif topology doğrulaması beklenen broker varlığını bulamadığında yükselir (K3: fail-fast)."""

    def __init__(self, missing: list[str]) -> None:
        self.missing = list(missing)
        joined = ", ".join(self.missing)
        super().__init__(
            f"Broker topology doğrulaması başarısız; eksik varlıklar: {joined}. "
            "Tek declarer backend'dir (K3); topology kurulmadan consumer başlatılmaz."
        )
