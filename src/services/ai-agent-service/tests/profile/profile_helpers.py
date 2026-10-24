"""tests/profile yardımcıları (L005 kuralı: conftest DEĞİL, benzersiz adlı modül).

``tests/profile`` bir paket DEĞİLDİR (``__init__.py`` yok): stdlib ``profile``
modülünü gölgelememek için. Modül adı benzersizdir (``profile_helpers``).

Canonical profile content is read from ``resolve_profile_dir()``; corruption and revision
senaryoları geçici dizin kopyalarında üretilir.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent_core.models import (
    BudgetProfile,
    ConversationTopic,
    ConversationTurn,
    DomainProgress,
    ExecutionContext,
)
from agent_core.profile import CanonicalProfileRepository, ProfileDocument, resolve_profile_dir

NOW = datetime(2026, 10, 22, 9, 0, 0, tzinfo=timezone.utc)


def run(coroutine: Any) -> Any:
    return asyncio.run(coroutine)


def canonical_dir() -> Path:
    return resolve_profile_dir()


def canonical_document() -> ProfileDocument:
    return CanonicalProfileRepository(canonical_dir()).current_document()


def copy_profile(tmp_path: Path, name: str = "author-profile") -> Path:
    target = tmp_path / name
    shutil.copytree(canonical_dir(), target)
    return target


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_manifest(directory: Path, **changes: Any) -> None:
    manifest = read_json(directory / "manifest.json")
    manifest.update(changes)
    (directory / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def rewrite_profile(
    directory: Path,
    mutate: Callable[[dict], None],
    *,
    revision: int | None = None,
    update_hash: bool = True,
) -> str:
    """profile.json'u değiştirir; ``update_hash`` ise manifest hash'ini yeniden hesaplar."""

    content = read_json(directory / "profile.json")
    mutate(content)
    raw = json.dumps(content, ensure_ascii=False, indent=2).encode("utf-8")
    (directory / "profile.json").write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    changes: dict[str, Any] = {}
    if update_hash:
        changes["content_hash"] = digest
    if revision is not None:
        changes["revision"] = revision
    if changes:
        write_manifest(directory, **changes)
    return digest


def section_by_id(content: dict, section_id: str) -> dict:
    for section in content["sections"]:
        if section["section_id"] == section_id:
            return section
    raise KeyError(section_id)


def budget_profile(**overrides: Any) -> BudgetProfile:
    defaults: dict[str, Any] = dict(
        name="profile-test", max_model_calls=4, max_total_tokens=40000, max_duration_seconds=30.0
    )
    defaults.update(overrides)
    return BudgetProfile(**defaults)


def make_v2_context(
    question: str,
    *,
    topic: str = "who_am_i",
    language: str = "tr",
    mode_preference: str = "auto",
    history: list[tuple[str, str]] | None = None,
    snapshot: Any = "canonical",
    **overrides: Any,
) -> ExecutionContext:
    """v2 bağlamı: who_am_i veya auto konu + pinlenmiş canonical snapshot."""

    pinned = canonical_document().snapshot if snapshot == "canonical" else snapshot
    turns = [
        ConversationTurn(role=role, content=content, created_at=NOW) for role, content in (history or [])
    ]
    defaults: dict[str, Any] = dict(
        run_id="run-profile-1",
        conversation_id="conv-profile-1",
        question=question,
        language=language,
        mode_preference=mode_preference,
        budget_profile=budget_profile(),
        conversation_topic=ConversationTopic(topic),
        profile_snapshot=pinned,
        conversation_history=turns,
    )
    defaults.update(overrides)
    return ExecutionContext(**defaults)
