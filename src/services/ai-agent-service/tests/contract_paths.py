"""Sözleşme testleri için tek kaynak yolları (src/contracts/agent).

v1 adları (``V1_DIR``, ``MANIFEST``, ``CONTRACT``, ``ENVELOPE_SCHEMA``,
``read_fixture``, ``read_payload_schema``) değişmez; v2 karşılıkları ``V2_``
önekiyle eklenir. ``CONTRACTS_BY_VERSION`` sürüm başına contract.json'u verir
(registry ↔ contract.json denklik testleri sürüm bazında koşar).
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = next(
    parent for parent in Path(__file__).resolve().parents if (parent / "src" / "contracts" / "agent").is_dir()
)
CONTRACTS_ROOT = REPO_ROOT / "src" / "contracts" / "agent"
V1_DIR = CONTRACTS_ROOT / "v1"
V2_DIR = CONTRACTS_ROOT / "v2"
FIXTURES_DIR = CONTRACTS_ROOT / "fixtures"
V2_FIXTURES_DIR = FIXTURES_DIR / "v2"

MANIFEST: dict = json.loads((FIXTURES_DIR / "manifest.json").read_text(encoding="utf-8"))
CONTRACT: dict = json.loads((V1_DIR / "contract.json").read_text(encoding="utf-8"))
ENVELOPE_SCHEMA: dict = json.loads((V1_DIR / "envelope.schema.json").read_text(encoding="utf-8"))

V2_MANIFEST: dict = json.loads((V2_FIXTURES_DIR / "manifest.json").read_text(encoding="utf-8"))
V2_CONTRACT: dict = json.loads((V2_DIR / "contract.json").read_text(encoding="utf-8"))
V2_ENVELOPE_SCHEMA: dict = json.loads((V2_DIR / "envelope.schema.json").read_text(encoding="utf-8"))

#: Sürüm → sözleşme dizini / contract.json (registry denklik testleri).
CONTRACT_DIRS: dict[int, Path] = {1: V1_DIR, 2: V2_DIR}
CONTRACTS_BY_VERSION: dict[int, dict] = {1: CONTRACT, 2: V2_CONTRACT}


def read_fixture(relative_path: str) -> str:
    return (FIXTURES_DIR / relative_path).read_text(encoding="utf-8")


def read_payload_schema(payload_schema: str) -> dict:
    return json.loads((V1_DIR / payload_schema).read_text(encoding="utf-8"))


def read_v2_fixture(relative_path: str) -> str:
    return (V2_FIXTURES_DIR / relative_path).read_text(encoding="utf-8")


def read_v2_payload_schema(payload_schema: str) -> dict:
    return json.loads((V2_DIR / payload_schema).read_text(encoding="utf-8"))
