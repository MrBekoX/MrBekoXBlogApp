"""FileCheckpointStore: kalıcı saklama, güvenli kimlikler ve eşzamanlılık sözleşmesi.

Plan A8 kabul bağlamı: "agent state'ini CheckpointStore portu üzerinden
kalıcı saklama" ve "aynı checkpoint'e eşzamanlı yazmayı desteklemediğin
durumları açık sözleşmeyle bildirme".
"""

from __future__ import annotations

import asyncio

import pytest

from agent_core.checkpoint import FileCheckpointStore
from agent_core.errors import AgentErrorCode, PortError
from agent_core.ports import CheckpointStore

from .conftest import run


def test_structurally_satisfies_port_and_is_not_a_test_double(tmp_path) -> None:
    """Store portu yapısal olarak doldurur; dev gerçekleştirimi double değildir."""
    store = FileCheckpointStore(tmp_path)
    assert isinstance(store, CheckpointStore)
    assert not hasattr(store, "is_test_double") or store.is_test_double is not True


def test_save_load_roundtrip(tmp_path) -> None:
    """Yazılan payload birebir okunur; belirli ve en-son okuma doğru çalışır."""
    store = FileCheckpointStore(tmp_path)

    run(store.save("run-1", "prepared:run", b"birinci-payload"))
    run(store.save("run-1", "state:exec-x", b"ikinci-payload"))

    assert run(store.load("run-1", "prepared:run")) == b"birinci-payload"
    checkpoint_id, payload = run(store.load_latest("run-1"))
    assert checkpoint_id == "state:exec-x"
    assert payload == b"ikinci-payload"


def test_persistence_survives_store_reopen(tmp_path) -> None:
    """Kalıcılık: YENİ depo örneği (süreç restart benzetimi) payload'ları okur.

    [LG-PERSISTENCE#C2]: bellek içi saver süreç restart'ında kaybeder; bu
    gerçekleştirim korur.
    """
    first = FileCheckpointStore(tmp_path)
    run(first.save("run-1", "prepared:run", b"kalici-payload"))

    reopened = FileCheckpointStore(tmp_path)
    checkpoint_id, payload = run(reopened.load_latest("run-1"))
    assert checkpoint_id == "prepared:run"
    assert payload == b"kalici-payload"


def test_load_missing_raises_not_found(tmp_path) -> None:
    store = FileCheckpointStore(tmp_path)

    with pytest.raises(PortError) as excinfo:
        run(store.load("run-1", "yok"))
    assert excinfo.value.code is AgentErrorCode.NOT_FOUND

    with pytest.raises(PortError) as excinfo:
        run(store.load_latest("run-yok"))
    assert excinfo.value.code is AgentErrorCode.NOT_FOUND


@pytest.mark.parametrize("bad", ["../kacti", "a/b", "a\\b", "", "   ", ".gizli"])
def test_unsafe_identifiers_rejected(tmp_path, bad: str) -> None:
    """Yol ayırıcı ve gezinme içeren kimlikler reddedilir; dizin dışına yazım yok."""
    store = FileCheckpointStore(tmp_path)

    with pytest.raises(PortError) as excinfo:
        run(store.save(bad, "cp", b"x"))
    assert excinfo.value.code is AgentErrorCode.VALIDATION_ERROR

    with pytest.raises(PortError):
        run(store.load("run-1", bad))

    # Depo kökü dışına hiçbir şey yazılmadı.
    assert not (tmp_path / "kacti").exists()


def test_overwrite_same_checkpoint_id(tmp_path) -> None:
    """Aynı kimliğe yeniden yazım üzerine yazar (port sözleşmesi)."""
    store = FileCheckpointStore(tmp_path)
    run(store.save("run-1", "prepared:run", b"eski"))
    run(store.save("run-1", "prepared:run", b"yeni"))

    assert run(store.load("run-1", "prepared:run")) == b"yeni"
    _, payload = run(store.load_latest("run-1"))
    assert payload == b"yeni"


def test_concurrent_write_to_same_run_rejected(tmp_path) -> None:
    """EŞZAMANLILIK SÖZLEŞMESİ: aynı run'a eşzamanlı ikinci yazım açık hatayla reddedilir."""
    store = FileCheckpointStore(tmp_path)

    async def scenario() -> tuple[int, PortError | None]:
        results = await asyncio.gather(
            store.save("run-1", "cp-a", b"a"),
            store.save("run-1", "cp-b", b"b"),
            return_exceptions=True,
        )
        succeeded = sum(1 for r in results if not isinstance(r, BaseException))
        failure = next((r for r in results if isinstance(r, PortError)), None)
        return succeeded, failure

    succeeded, failure = run(scenario())
    assert succeeded == 1
    assert failure is not None
    assert failure.code is AgentErrorCode.VALIDATION_ERROR
    assert "eşzamanlı" in failure.message

    # Reddedilen yazım depoya sızmaz: iki kimlikten yalnız biri okunur.
    loaded: list[bytes] = []
    missing = 0
    for cp in ("cp-a", "cp-b"):
        try:
            loaded.append(run(store.load("run-1", cp)))
        except PortError as error:
            assert error.code is AgentErrorCode.NOT_FOUND
            missing += 1
    assert len(loaded) == 1 and missing == 1
    assert loaded[0] in (b"a", b"b")


def test_sequential_writes_and_other_runs_unaffected(tmp_path) -> None:
    """Sıralı yazımlar serbesttir; farklı run'ların eşzamanlı yazıları çakışmaz."""
    store = FileCheckpointStore(tmp_path)

    async def scenario() -> None:
        await asyncio.gather(
            store.save("run-1", "cp-a", b"a"),
            store.save("run-2", "cp-b", b"b"),
        )
        await store.save("run-1", "cp-c", b"c")

    run(scenario())
    assert run(store.load("run-1", "cp-a")) == b"a"
    assert run(store.load("run-2", "cp-b")) == b"b"
    assert run(store.load("run-1", "cp-c")) == b"c"
