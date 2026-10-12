"""B1 sözleşme testleri için tek kaynak yolları (src/contracts/agent)."""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = next(
    parent for parent in Path(__file__).resolve().parents if (parent / "src" / "contracts" / "agent").is_dir()
)
V1_DIR = REPO_ROOT / "src" / "contracts" / "agent" / "v1"
FIXTURES_DIR = REPO_ROOT / "src" / "contracts" / "agent" / "fixtures"

MANIFEST: dict = json.loads((FIXTURES_DIR / "manifest.json").read_text(encoding="utf-8"))
CONTRACT: dict = json.loads((V1_DIR / "contract.json").read_text(encoding="utf-8"))
ENVELOPE_SCHEMA: dict = json.loads((V1_DIR / "envelope.schema.json").read_text(encoding="utf-8"))


def read_fixture(relative_path: str) -> str:
    return (FIXTURES_DIR / relative_path).read_text(encoding="utf-8")


def read_payload_schema(payload_schema: str) -> dict:
    return json.loads((V1_DIR / payload_schema).read_text(encoding="utf-8"))
