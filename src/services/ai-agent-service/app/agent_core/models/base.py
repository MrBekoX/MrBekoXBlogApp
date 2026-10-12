"""İş modeli temel sınıfı ve paylaşılan kısıtlı tipler.

Tüm iş modelleri ``extra="forbid"`` ile tanımlanır: alan kümesi JSON
sözleşmesinin ta kendisidir, fazladan alan veri kaybına değil hataya yol açar
[PYDANTIC-MODELS#C2]. Zaman damgaları tz-aware olmak zorundadır ve UTC'ye
çevrilerek saklanır (W0 §6.3: UTC ISO 8601).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints, WrapValidator

__all__ = [
    "BusinessModel",
    "HashHex",
    "Identifier",
    "LanguageCode",
    "NonEmptyText",
    "UtcDatetime",
    "ensure_utc",
]

ISO_ZULU = "%Y-%m-%dT%H:%M:%SZ"


def ensure_utc(value: datetime) -> datetime:
    """tz-aware datetime ister ve UTC'ye çevirir; naive girdiyi reddeder."""

    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError("zaman damgası timezone bilgisi taşımalıdır (UTC bekleniyor)")
    return value.astimezone(timezone.utc)


def _utc_or_none(value: datetime | None, handler) -> datetime | None:
    if value is None:
        return None
    return ensure_utc(handler(value))


UtcDatetime = Annotated[datetime, WrapValidator(_utc_or_none)]

#: Küçük/boş tanımlayıcı kabul etmez; backend tarafından üretilir (A0 §7.4).
Identifier = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]

#: İnsan-okur zorunlu metin.
NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20000)]

#: tr / en / tr-TR biçiminde dil kodu.
LanguageCode = Annotated[str, StringConstraints(pattern=r"^[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})?$")]

#: UTF-8 SHA-256 özeti, küçük harf onaltılık (A0 §7.2).
HashHex = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class BusinessModel(BaseModel):
    """Tüm iş modellerinin temeli: bilinmeyen alan reddedilir, atama doğrulanır."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)
