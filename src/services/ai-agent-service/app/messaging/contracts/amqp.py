"""AMQP properties eşlemesi: zarf ile tutarlı broker alanları (plan satır 233).

Yayın katmanı (B2/B3) bu sözlüğü RabbitMQ basic properties'lerine kopyalar;
content_type daima application/json'dır ve gövde pickle/serbest nesne değil JSON'dur.
"""

from __future__ import annotations

from .envelope import AgentEnvelope

__all__ = ["to_amqp_properties"]


def to_amqp_properties(envelope: AgentEnvelope) -> dict[str, str]:
    """Zarf alanlarından AMQP basic properties sözlüğü üretir.

    message_id ve correlation_id zarftaki değerlerle birebir; type mesaj türünün
    makine-okur adıdır; timestamp bilinçli olarak taşınmaz (kesirli saniye kaybı
    yerine UTC ISO 8601 occurred_at zarfta kalır).
    """

    return {
        "message_id": envelope.message_id,
        "correlation_id": envelope.correlation_id,
        "content_type": "application/json",
        "type": envelope.message_type,
    }
