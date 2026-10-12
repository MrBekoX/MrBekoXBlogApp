"""Kategorize sözleşme ihlali türü.

Kategoriler fixtures/manifest.json 'reason' değerleriyle ve .NET tarafındaki
``AgentContractErrorCategory`` ile birebir aynıdır; her iki doğrulayıcı aynı
fixture için aynı kategoriyi üretir.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = ["AgentContractError", "ContractErrorCategory"]


class ContractErrorCategory(StrEnum):
    """Sözleşme ihlali kategorileri (plan kabul ölçütü, 02-rabbitmq-haberlesme-plani.md:241)."""

    MISSING_FIELD = "missing_field"
    UNKNOWN_VERSION = "unknown_version"
    UNKNOWN_TYPE = "unknown_type"
    OVERSIZED = "oversized"
    WRONG_TYPE = "wrong_type"
    BAD_FORMAT = "bad_format"
    EXTRA_FIELD = "extra_field"
    PRODUCER_MISMATCH = "producer_mismatch"


class AgentContractError(Exception):
    """Kategorize edilmiş tek sözleşme ihlali.

    Attributes:
        category: Makine-okur kategori (``ContractErrorCategory``).
        field: İhlalin alan yolu (ör. ``payload.usage.run_id``).
        message: İnsan-okur açıklama.
    """

    def __init__(self, category: ContractErrorCategory, field: str, message: str) -> None:
        super().__init__(f"{category.value} ({field}): {message}")
        self.category = category
        self.field = field
        self.message = message
