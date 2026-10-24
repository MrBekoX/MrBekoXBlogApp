"""Ortak hata sözleşmesi.

Hata türleri tüm portlar ve iş modelleri için ortaktır; kaynak:
``docs/ai-agent-plan/agent-architecture.md`` §5 ve W0 kararları §1.5.
Bu modül transport'tan bağımsızdır; AMQP/HTTP kavramı içermez.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = ["AgentErrorCode", "PortError"]


class AgentErrorCode(StrEnum):
    """Port ve sonuç hata kodları. B1, bu değerleri olay payload'larında kod olarak taşır."""

    CONFIG_ERROR = "config_error"
    VALIDATION_ERROR = "validation_error"
    NOT_FOUND = "not_found"
    STALE_SNAPSHOT = "stale_snapshot"
    BUDGET_EXHAUSTED = "budget_exhausted"
    CANCELLED = "cancelled"
    PROVIDER_ERROR = "provider_error"
    TIMEOUT = "timeout"


class PortError(Exception):
    """Port ve giriş noktası hatalarının tek tipi.

    Attributes:
        code: Makine-okur hata kodu (``AgentErrorCode``).
        message: İnsan-okur açıklama; ``config_error`` için yapılandırma
            düzeltmesini göstermelidir.
        port: Hatanın kaynağı olan port/giriş noktası adı (ör. ``"ModelProvider"``).
        retryable: Aynı girdiyle tekrar denemenin anlamlı olup olmadığı.
    """

    def __init__(
        self,
        code: AgentErrorCode,
        message: str,
        *,
        port: str | None = None,
        retryable: bool = False,
        usage_uncertain: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.port = port
        self.retryable = retryable
        self.usage_uncertain = usage_uncertain

    def __str__(self) -> str:
        if self.port:
            return f"[{self.code.value}] {self.port}: {self.message}"
        return f"[{self.code.value}] {self.message}"
