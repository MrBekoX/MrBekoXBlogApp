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
    "BAD_FORMAT_ERROR_TYPE",
    "HashHex",
    "Identifier",
    "LanguageCode",
    "ProfileIdString",
    "SectionIdString",
    "StrictBool",
    "StrictFloat",
    "StrictInt",
    "TraceParent",
    "UtcIsoString",
    "UuidString",
    "bad_format_error",
]

_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_UTC_ISO_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?Z$")
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_LANGUAGE_RE = re.compile(r"^[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})?$")
_TRACEPARENT_RE = re.compile(r"^[0-9a-f]{2}-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$")
#: v2 profil kimlikleri (src/contracts/agent/v2/common.schema.json profile_id/section_id).
_PROFILE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_SECTION_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,127}$")

#: Model içi çapraz biçim kuralının Pydantic hata türü; doğrulayıcı ``bad_format``
#: kategorisine eşler (``utc_format`` ile aynı desen; .NET doğrulayıcıyla aynı kategori).
BAD_FORMAT_ERROR_TYPE = "bad_format"

UtcFormats = ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ")


def bad_format_error(message: str) -> PydanticCustomError:
    """Şemanın ``pattern`` ile ifade ettiği ya da çapraz biçim kuralı ihlali (``bad_format``)."""

    return PydanticCustomError(BAD_FORMAT_ERROR_TYPE, message)


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
ProfileIdString = Annotated[str, StringConstraints(pattern=_PROFILE_ID_RE.pattern)]
SectionIdString = Annotated[str, StringConstraints(pattern=_SECTION_ID_RE.pattern)]

#: Backend/agent tarafından üretilen kısa tanımlayıcı (A1 Identifier ile aynı sınırdır).
Identifier = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
