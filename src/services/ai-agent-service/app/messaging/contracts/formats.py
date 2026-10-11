"""Sözleşme biçim türleri: kanonik UUID, 'Z' sonekli UTC ISO 8601, SHA-256 hex,
dil kodu ve W3C traceparent. Kaynak: src/contracts/agent/v1/common.schema.json.

Kural kümesi .NET ``AgentContractFormats`` ile aynıdır; takvim geçerliliği
(ör. 2026-13-99) her iki tarafta da reddedilir.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated

from pydantic import AfterValidator, Strict, StringConstraints
from pydantic_core import PydanticCustomError

__all__ = [
    "HashHex",
    "Identifier",
    "LanguageCode",
    "StrictBool",
    "StrictFloat",
    "StrictInt",
    "TraceParent",
    "UtcIsoString",
    "UuidString",
]

_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_UTC_ISO_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?Z$")
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_LANGUAGE_RE = re.compile(r"^[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})?$")
_TRACEPARENT_RE = re.compile(r"^[0-9a-f]{2}-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$")

UtcFormats = ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ")


def _validate_utc_iso(value: str) -> str:
    """Kalıbı geçen zamanın takvim geçerliliğini doğrular; 'Z' soneki UTC'yi sabitler."""

    for fmt in UtcFormats:
        try:
            datetime.strptime(value, fmt)
            return value
        except ValueError:
            continue
    raise PydanticCustomError(
        "utc_format",
        "zaman damgası tanımlı bir UTC anı olmalıdır (ISO 8601, 'Z' sonekli)",
    )


StrictInt = Annotated[int, Strict()]
StrictFloat = Annotated[float, Strict()]
StrictBool = Annotated[bool, Strict()]

UuidString = Annotated[str, StringConstraints(pattern=_UUID_RE.pattern)]
UtcIsoString = Annotated[
    str,
    StringConstraints(pattern=_UTC_ISO_RE.pattern),
    AfterValidator(_validate_utc_iso),
]
HashHex = Annotated[str, StringConstraints(pattern=_HASH_RE.pattern)]
LanguageCode = Annotated[str, StringConstraints(pattern=_LANGUAGE_RE.pattern)]
TraceParent = Annotated[str, StringConstraints(pattern=_TRACEPARENT_RE.pattern)]

#: Backend/agent tarafından üretilen kısa tanımlayıcı (A1 Identifier ile aynı sınırdır).
Identifier = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
